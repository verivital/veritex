import onnx
import onnxruntime as ort
from onnx import numpy_helper
import gzip
import torch
from torch import nn
import onnx2pytorch
import spconv

def load_onnx(path):
    if path.endswith('.gz'):
        onnx_model = onnx.load(gzip.GzipFile(path))
    else:
        onnx_model = onnx.load(path)
    return onnx_model

def load_model_onnx(path, input_shape, compute_test_acc=False, force_convert=False):
    # pip install onnx2pytorch
    onnx_model = load_onnx(path)

    onnx_input_dims = onnx_model.graph.input[0].type.tensor_type.shape.dim
    onnx_shape = tuple(d.dim_value for d in onnx_input_dims[1:])
    input_shape = tuple(input_shape)
    pytorch_model = onnx2pytorch.ConvertModel(onnx_model)

    if force_convert:
        new_modules = []
        modules = list(pytorch_model.modules())[1:]
        for mi, m in enumerate(modules):
            if isinstance(m, torch.nn.Linear):
                new_m = nn.Linear(in_features=m.in_features, out_features=m.out_features, bias=m.bias is not None)
                new_m.weight.data.copy_(m.weight.data)
                new_m.bias.data.copy_(m.bias)
                new_modules.append(new_m)
            elif isinstance(m, torch.nn.ReLU):
                new_modules.append(torch.nn.ReLU())
            elif isinstance(m, onnx2pytorch.operations.flatten.Flatten):
                new_modules.append(torch.nn.Flatten())
            else:
                raise NotImplementedError

        seq_model = nn.Sequential(*new_modules)
        return seq_model

    if len(input_shape) <= 2:
        return pytorch_model

    # Check model input shape.
    is_channel_last = False
    if onnx_shape != input_shape:
        # Change channel location.
        onnx_shape = onnx_shape[2:] + onnx_shape[:2]
        if onnx_shape == input_shape:
            is_channel_last = True
        else:
            print(f"Unexpected input shape in onnx: {onnx_shape}, given {input_shape}")

    # Fixup converted ONNX model. For ResNet we directly return; for other models, we convert them to a Sequential model.
    # We also need to handle NCHW and NHWC formats here.
    conv_c, conv_h, conv_w = input_shape
    modules = list(pytorch_model.modules())[1:]
    new_modules = []
    need_permute = False
    for mi, m in enumerate(modules):
        if isinstance(m, onnx2pytorch.operations.add.Add):
            # ResNet model. No need to convert to sequential.
            return pytorch_model, is_channel_last
        if isinstance(m, torch.nn.Conv2d):
            # Infer the output size of conv.
            conv_h, conv_w = conv_output_shape((conv_h, conv_w), m.kernel_size, m.stride, m.padding)
            conv_c = m.weight.size(0)
        if isinstance(m, onnx2pytorch.operations.reshape.Reshape):
            # Replace reshape with flatten.
            new_modules.append(nn.Flatten())
            # May need to permute the next linear layer if the model was in NHWC format.
            need_permute = True and is_channel_last
        elif isinstance(m, torch.nn.Linear) and need_permute:
            # The original model is in NHWC format and we now have NCHW format, so the dense layer's weight must be adjusted.
            new_m = nn.Linear(in_features=m.in_features, out_features=m.out_features, bias=m.bias is not None)
            new_m.weight.data.copy_(m.weight.view(m.weight.size(0), conv_h, conv_w, conv_c).permute(0, 3, 1, 2).contiguous().view(m.weight.size(0), -1))
            new_m.bias.data.copy_(m.bias)
            need_permute = False
            new_modules.append(new_m)
        elif isinstance(m, torch.nn.ReLU) and mi == (len(modules)-1):
            # not add relu if last layer is relu
            pass
        # else:
        #     new_modules.append(m)
        elif isinstance(m, torch.nn.ReLU):
            new_modules.append(m)
        elif isinstance(m, torch.nn.Linear):
            new_modules.append(m)
        elif isinstance(m, torch.nn.Conv2d):
            new_modules.append(m)

    seq_model = nn.Sequential(*new_modules)
    for param in seq_model.parameters():
        param.requires_grad = False

    if compute_test_acc:
        get_test_acc(seq_model, input_shape)

    return seq_model, is_channel_last



def conv_output_shape(h_w, kernel_size=1, stride=1, pad=0, dilation=1):
    """
    Utility function for computing output of convolutions
    takes a tuple of (h,w) and returns a tuple of (h,w)
    """
    if type(h_w) is not tuple:
        h_w = (h_w, h_w)
    if type(kernel_size) is not tuple:
        kernel_size = (kernel_size, kernel_size)
    if type(stride) is not tuple:
        stride = (stride, stride)
    if type(pad) is not tuple:
        pad = (pad, pad)
    h = (h_w[0] + (2 * pad[0]) - (dilation * (kernel_size[0] - 1)) - 1) // stride[0] + 1
    w = (h_w[1] + (2 * pad[1]) - (dilation * (kernel_size[1] - 1)) - 1) // stride[1] + 1
    return h, w



def get_test_acc(model, input_shape, is_channel_last=False):
    import torchvision
    import torchvision.transforms as transforms
    if input_shape == (3, 32, 32):
        testset = torchvision.datasets.CIFAR10(root='./data', train=False, download=True, transform=transforms.Compose([transforms.ToTensor()]))
    elif input_shape == (1, 28, 28):
        testset = torchvision.datasets.MNIST(root='./data', train=False, download=True, transform=transforms.Compose([transforms.ToTensor()]))
    else:
        raise RuntimeError("Unable to determine dataset for test accuracy.")
    testloader = torch.utils.data.DataLoader(testset, batch_size=1, shuffle=False, num_workers=2)
    total = 0
    correct = 0
    for data in testloader:
        images, labels = data
        if is_channel_last:
            images = images.permute(0,2,3,1)
        outputs = model(images)
        _, predicted = torch.max(outputs.data, 1)
        total += labels.size(0)
        correct +=  (predicted == labels).sum().item()
    print(f'correct {correct} of {total}')