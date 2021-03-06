#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Mar 25 13:14:06 2020

@author: mishugeb
"""
"""
Implementation of non-negative matrix factorization for GPU
"""

from datetime import datetime

from nimfa.methods.seeding import nndsvd
import numpy as np
import torch
import torch.nn
from torch import nn



class NMF:
    def __init__(self, V, Y, rank, lambda_c = 1e-40, lambda_pen = .5, lr = 0.002, report_loss = 200, max_iterations=200000, tolerance=1e-8, test_conv=1000, gpu_id=0, generator=None,
                 init_method='nndsvd', floating_point_precision='single', min_iterations=2000):

        """
        Run non-negative matrix factorisation using GPU. Uses beta-divergence.

        Args:
          V: Matrix to be factorised
          rank: (int) number of latent dimensnions to use in factorisation
          max_iterations: (int) Maximum number of update iterations to use during fitting
          tolerance: tolerance to use in convergence tests. Lower numbers give longer times to convergence
          test_conv: (int) How often to test for convergnce
          gpu_id: (int) Which GPU device to use
          generator: random generator, if None (default) datetime is used
          init_method: how to initialise basis and coefficient matrices, options are:
            - random (will always be the same if set generator != None)
            - NNDSVD
            - NNDSVDa (fill in the zero elements with the average),
            - NNDSVDar (fill in the zero elements with random values in the space [0:average/100]).
          floating_point_precision: (string or type). Can be `double`, `float` or any type/string which
              torch can interpret.
          min_iterations: the minimum number of iterations to execute before termination. Useful when using
              fp32 tensors as convergence can happen too early.
        """
        #torch.cuda.set_device(gpu_id)

        if floating_point_precision == 'single':
            self._tensor_type = torch.FloatTensor
            self._np_dtype = np.float32
        elif floating_point_precision == 'double':
            self._tensor_type = torch.DoubleTensor
            self._np_dtype = np.float64
        else:
            raise ValueError("Precision needs to be either 'single' or 'double'." )

        self.max_iterations = max_iterations
        self.min_iterations = min_iterations

        # If V is not in a batch, put it in a batch of 1
        if len(V.shape) == 2:
            V = V[None, :, :]

        if len(Y.shape) == 2:
            Y = Y[None, :, :]

        self._V = V.type(self._tensor_type)
        self._Y = Y.type(self._tensor_type)
        self._Y_max = torch.argmax(self._Y, dim= 1)
        self._fix_neg = nn.Threshold(0., 1e-20)
        self._tolerance = tolerance
        self._prev_loss = None
        self._iter = 0
        self._test_conv = test_conv
        #self._gpu_id = gpu_id
        self._rank = rank
        self._lambda_c = lambda_c
        self._lambda_pen = lambda_pen
        self._lr = lr
        self._report_loss = report_loss
        self._generator = generator
        self._W, self._H, self._B= self._initialise_wh(init_method)

    def _initialise_wh(self, init_method):
        """
        Initialise basis and coefficient matrices according to `init_method`
        """
        if init_method == 'random':
            W = torch.unsqueeze(torch.from_numpy(self._generator.random((self._V.shape[1],self._rank), dtype=np.float64)),0)
            H = torch.unsqueeze(torch.from_numpy(self._generator.random((self._rank, self._V.shape[2]), dtype=np.float64)),0)
            B = torch.unsqueeze(torch.from_numpy(self._generator.random((self._Y.shape[1], self._rank), dtype=np.float64)), 0)
            if self._np_dtype is np.float32:
                W = W.float()
                H = H.float()
                B = B.float()

            return W, H, B
        #
        # elif init_method == 'nndsvd':
        #     W = np.zeros([self._V.shape[0], self._V.shape[1], self._rank])
        #     H = np.zeros([self._V.shape[0], self._rank, self._V.shape[2]])
        #     nv = nndsvd.Nndsvd()
        #     for i in range(self._V.shape[0]):
        #         vin = np.mat(self._V.cpu().numpy()[i])
        #         W[i,:,:], H[i,:,:] = nv.initialize(vin, self._rank, options={'flag': 0})
        #
        # elif init_method == 'nndsvda':
        #     W = np.zeros([self._V.shape[0], self._V.shape[1], self._rank])
        #     H = np.zeros([self._V.shape[0], self._rank, self._V.shape[2]])
        #     nv = nndsvd.Nndsvd()
        #     for i in range(self._V.shape[0]):
        #         vin = np.mat(self._V.cpu().numpy()[i])
        #         W[i,:,:], H[i,:,:] = nv.initialize(vin, self._rank, options={'flag': 1})
        #
        # elif init_method == 'nndsvdar':
        #     W = np.zeros([self._V.shape[0], self._V.shape[1], self._rank])
        #     H = np.zeros([self._V.shape[0], self._rank, self._V.shape[2]])
        #     nv = nndsvd.Nndsvd()
        #     for i in range(self._V.shape[0]):
        #         vin = np.mat(self._V.cpu().numpy()[i])
        #         W[i,:,:], H[i,:,:] = nv.initialize(vin, self._rank, options={'flag': 2})
        # elif init_method =='nndsvd_min':
        #    W = np.zeros([self._V.shape[0], self._V.shape[1], self._rank])
        #    H = np.zeros([self._V.shape[0], self._rank, self._V.shape[2]])
        #    nv = nndsvd.Nndsvd()
        #    for i in range(self._V.shape[0]):
        #        vin = np.mat(self._V.cpu().numpy()[i])
        #        w, h = nv.initialize(vin, self._rank, options={'flag': 2})
        #        min_X = np.min(vin[vin>0])
        #        h[h <= min_X] = min_X
        #        w[w <= min_X] = min_X
        #        #W= np.expand_dims(W, axis=0)
        #        #H = np.expand_dims(H, axis=0)
        #        W[i,:,:]=w
        #        H[i,:,:]=h
        # W,H=initialize_nm(vin, nfactors, init=init, eps=1e-6,random_state=None)
        # W = torch.from_numpy(W).type(self._tensor_type)
        # H = torch.from_numpy(H).type(self._tensor_type)
        # return W, H

    @property
    def reconstruction(self):
        return self.W @ self.H

    @property
    def W(self):
        # Signatures
        # S -> (N, 96)
        return self._W

    @property
    def H(self):
        # Exposure
        # E -> (N, K)
        return self._H

    @property
    def B(self):
        # Weights of Logistic Regression
        # W -> (K, C)
        return self._B

    @property
    def Y_hat(self):
        # Y_hat = softmax(W E)
        # Y_hat -> (C, N)
        Z = self.B @ self.H
        # e_x = np.exp(Z - np.max(Z, axis = -1, keepdims= True) )
        e_x = np.exp(Z - torch.max(Z, 1)[0].unsqueeze(dim=1))
        e_x_sum = torch.sum(e_x, 1).unsqueeze(dim=1)
        e_x_sum[e_x_sum == 0] = 1e-8
        # print(e_x_sum)
        return e_x / e_x_sum + 1e-30

    @property
    def conv(self):
        try:
            return self._conv
        except: 
            return 0

    @property
    def _tot_loss(self):
        return self._fro_loss + self._lambda_c * self._ce_loss


    @property
    def _kl_loss(self):
        # calculate kl_loss in double precision for better convergence criteria
        return (self._V * (self._V / self.reconstruction).log()).sum(dtype=torch.float64) - self._V.sum(dtype=torch.float64) + self.reconstruction.sum(dtype=torch.float64)

    @property
    def _fro_loss(self):
        # calculate frobenius reconstruction error
        return (torch.norm(self._V - self.reconstruction, p = 'fro', dim=(1,2)))[0]


    @property
    def _ce_loss(self):
        '''
        Calculate Cross Entropy loss from one-hot encoded input
         L  = -1/n * Y log(Y_hat) + lam/2 * w^2
        '''
        # n = self._V.shape[2]
        # loss = (-1/n) *  torch.sum(self._Y * np.log(self.Y_hat))
        return - torch.sum(self._Y * np.log(self.Y_hat))

    @property
    def _acc(self):
        Y_pred = torch.argmax(self.Y_hat, dim = 1)
        return torch.sum(Y_pred == self._Y_max)/self._Y_max.shape[1]


    @property
    def generator(self):
        return self._generator

    @property
    def _loss_converged(self):
        """
        Check if loss has converged
        """
        if not self._iter:
            self._loss_init = self._kl_loss
        elif ((self._prev_loss - self._kl_loss) / self._loss_init) < self._tolerance:
            return True
        self._prev_loss = self._kl_loss
        return False

    def fit(self, beta=2, supervised = True):
        """
        Fit the basis (W) and coefficient (H) matrices to the input matrix (V) using multiplicative updates and
            beta divergence
        Args:
          beta: value to use for generalised beta divergence. Default is 1 for KL divergence
            beta == 2 => Euclidean updates
            beta == 1 => Generalised Kullback-Leibler updates
            beta == 0 => Itakura-Saito updates
        """
        with torch.no_grad():
            def stop_iterations():
                stop = (self._V.shape[0] == 1) and \
                       (self._iter % self._test_conv == 0) and \
                       self._loss_converged and \
                       (self._iter > self.min_iterations)
                if stop:
                    pass
                    #print("loss converged with {} iterations".format(self._iter))
                return  [stop, self._iter]

            if (beta == 2 and not supervised):
                for self._iter in range(self.max_iterations):
                    self._H = self.H * (self.W.transpose(1, 2) @ self._V) / (self.W.transpose(1, 2) @ (self.W @ self.H))
                    self._W = self.W * (self._V @ self.H.transpose(1, 2)) / (self.W @ (self.H @ self.H.transpose(1, 2)))

                    if stop_iterations()[0]:
                        self._conv=stop_iterations()[1]
                        break

            elif (beta == 2 and supervised):
                for self._iter in range(self.max_iterations):
                    self._H = self.H * ( (self.W.transpose(1, 2) @ self._V) - (self._lambda_c/2) * self.B.transpose(1,2) @ (self.Y_hat - self._Y) ) / (self.W.transpose(1, 2) @ (self.W @ self.H))
                    self._H[self._H < 0] = 1e-6

                    self._W = self.W * (self._V @ self.H.transpose(1, 2)) / (self.W @ (self.H @ self.H.transpose(1, 2)))
                    self._W[self._W < 0] = 1e-6
                    W_sum = torch.sum(self._W, 1).unsqueeze(dim=1)
                    W_sum[W_sum == 0] = 1e-8
                    self._W = self._W / W_sum
                    #avoid sum to 0
                    #TODO: Normalize signatures
                    # self._B = self.B - self._lr * (self.Y_hat - self._Y) @ self.H.transpose(1,2) + self._lambda_pen * self.B
                    self._B = self.B - self._lr * (self.Y_hat - self._Y) @ self.H.transpose(1,2)
                    # print(self._B)
                    # print(W_sum)
                    # print(self.Y_hat)
                    # print(self.H)
                    # print(torch.sum(self.W, 1))
                    if (self._iter % self._report_loss == 0):
                        print('Epoch: {:.0f} ; Ltot = {:.2f} ;  Lrec = {:.2f} ; Lce = {:.2f} ; acc = {:.3f}'.format(self._iter, self._tot_loss,  self._fro_loss, self._ce_loss, self._acc))

                    #     if torch.isnan(self._ce_loss):
                    #         print(self.Y_hat)
                    #         print(np.log(self.Y_hat))
                    #         break
                    #
                    # if (torch.any(torch.isnan(self.B))):
                    #     self._conv=stop_iterations()[1]
                    #     break
                    if stop_iterations()[0]:
                        self._conv=stop_iterations()[1]
                        break
            #
            # # Optimisations for the (common) beta=1 (KL) case.
            # elif beta == 1:
            #     ones = torch.ones(self._V.shape).type(self._tensor_type)
            #     for self._iter in range(self.max_iterations):
            #         ht = self.H.transpose(1, 2)
            #         numerator = (self._V / (self.W @ self.H)) @ ht
            #
            #         denomenator = ones @ ht
            #         self._W *= numerator / denomenator
            #
            #         wt = self.W.transpose(1, 2)
            #         numerator = wt @ (self._V / (self.W @ self.H))
            #         denomenator = wt @ ones
            #         self._H *= numerator / denomenator
            #         if stop_iterations()[0]:
            #             self._conv=stop_iterations()[1]
            #             break
            #
            # else:
            #     for self._iter in range(self.max_iterations):
            #         self._H = self.H * ((self.W.transpose(1, 2) @ (((self.W @ self.H) ** (beta - 2)) * self._V)) /
            #                            (self.W.transpose(1, 2) @ ((self.W @ self.H)**(beta-1))))
            #         self._W = self.W * ((((self.W@self.H)**(beta-2) * self._V) @ self.H.transpose(1, 2)) /
            #                            (((self.W @ self.H) ** (beta - 1)) @ self.H.transpose(1, 2)))
            #         if stop_iterations()[0]:
            #             self._conv=stop_iterations()[1]
            #             break
            #
