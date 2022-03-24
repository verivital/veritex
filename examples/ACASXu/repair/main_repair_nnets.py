
import logging
from acasxu_repair_list import *
from veritex.utils.load_onnx import load_ffnn_onnx, save_onnx
import multiprocessing
from veritex.methods.repair import REPAIR, DATA
import torch.optim as optim
import torch.nn as nn
import os



if __name__ == '__main__':
    # Creating and Configuring Logger
    logger = logging.getLogger()
    Log_Format = logging.Formatter('%(levelname)s %(asctime)s - %(message)s')
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler('neural_network_repair.log', 'w+')
    file_handler.setFormatter(Log_Format)
    logger.addHandler(file_handler)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(Log_Format)
    logger.addHandler(console_handler)

    num_processors = multiprocessing.cpu_count()
    for n in range(9,len(repair_list)):
        lr = 0.001
        epochs = 200
        alpha, beta = 1.0, 0.0
        item = repair_list[n]
        i, j = item[0][0], item[0][1]
        if (i==1 and j ==9) or (i==2 and j ==9):
            output_limit = 10
            lr = 0.01
        else:
            output_limit = 1000
        logging.info(f'Neural Network {i}{j}')
        properties_repair = item[1]
        nn_path = "../nets/ACASXU_run2a_" + str(i) + "_" + str(j) + "_batch_2000.onnx"
        torch_model = load_ffnn_onnx(nn_path)

        rp = REPAIR(torch_model, properties_repair, output_limit=output_limit)
        optimizer = optim.SGD(torch_model.parameters(), lr=lr, momentum=0.9)
        criterion = nn.MSELoss()
        savepath = './logs'
        if not os.path.isdir(savepath):
            os.mkdir(savepath)
        savepath += '/nnet'+str(i)+str(j)+'_lr'+str(lr)+'_epochs'+str(epochs)+'_alpha'+str(alpha)+'_beta'+str(beta)
        if not os.path.isdir(savepath):
            os.mkdir(savepath)

        rp.repair_model_classification(optimizer, criterion, alpha, beta, savepath, epochs=epochs)
        logging.info('\n****************************************************************\n')



