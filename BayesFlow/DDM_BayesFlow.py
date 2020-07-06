import sys
sys.path.append('../')

import tensorflow as tf
print(tf.__version__)
from tensorflow.keras.regularizers import l2
import tensorflow.contrib.eager as tfe
import tensorflow_probability as tfp
import numpy as np
import seaborn as sns
from scipy import stats
import pandas as pd
from sklearn.metrics import r2_score
import matplotlib.pyplot as plt
import pickle

from functools import partial
from tqdm.notebook import tqdm
# print(tqdm.__version__)

from models import DeepConditionalModel, InvariantNetwork
from losses import maximum_likelihood_loss
from inn_utils import train_online_ml
# from viz import plot_losses, plot_metrics_params


from sklearn.neighbors import KernelDensity
import random
import multiprocessing as mp
import psutil
import pickle
import os
import re
import scipy as scp
from scipy.stats import gamma
import time

import cddm_data_simulation as cds
import kde_training_utilities as kde_util
import kde_class as kde
import boundary_functions as bf

tf.enable_eager_execution()


# Data generator function for 2-choice data using ddm_flexbound
def data_generator_ddm_flexbound(batch_size, n):
    v = np.random.uniform(-3, 3, batch_size)
    a = np.random.uniform(0.3, 2.5, batch_size)
    w = np.random.uniform(0.1, 0.9, batch_size)
    
    # Number of paths to be sampled for each batch    
    n_samples = 10000 
    
    # Bool to determine how to put 'rt' and 'choice_made' together
    multiply = True 
    
    boundary_function = bf.constant
        
    X_train = []

    for i in range(batch_size):
        out = cds.ddm_flexbound(v[i], 
                                a[i], 
                                w[i],
                                ndt = 0.5,
                                delta_t = 0.001, 
                                s = np.sqrt(2),
                                max_t = 20,
                                n_samples = n_samples,
                                boundary_fun = boundary_function,
                                boundary_multiplicative = True, 
                                boundary_params = {})
                                #boundary_params = {"theta": 0.01})
        if multiply:
            # Multiply 'rt' and 'choice_made'
            data = (out[0]*out[1]).reshape(n_samples, )
        else:        
            # concatenate 'rt' and 'choice_made'
            data = np.concatenate((out[0].T, out[1].T), axis=1).reshape(2*n_samples,) 
            
        X_train.append(data)    
        
    X_train = np.array(X_train)         
    # Concatenating a, v and w
    param = np.concatenate((a.reshape(-1, 1), v.reshape(-1, 1), w.reshape(-1, 1)), axis=1)
    
    return tf.convert_to_tensor(X_train, dtype=tf.float32), tf.convert_to_tensor(param, dtype=tf.float32)
    
# Data generator function for 2-choice data using Levy_flexbound
def data_generator_levy_flexbound(batch_size, n):
    v = np.random.uniform(-3, 3, batch_size)
    a = np.random.uniform(0.3, 2.0, batch_size)
    w = np.random.uniform(0.1, 0.9, batch_size)
    
    # Number of paths to be sampled for each batch    
    n_samples = 8000
    
    # Bool to determine how to put 'rt' and 'choice_made' together
    multiply = True 
        
    boundary_function = bf.constant
    
    X_train = []

    for i in range(batch_size):
        out = cds.levy_flexbound(v[i], 
                                 a[i],
                                 w[i],
                                 alpha_diff = 1.5,
                                 ndt = 0.5,
                                 delta_t = 0.001, 
                                 max_t = 20,
                                 n_samples = n_samples,
                                 boundary_fun = boundary_function,
                                 boundary_multiplicative = True, 
                                 boundary_params = {})
                                #boundary_params = {"theta": 0.01})
        if multiply:
            # Multiply 'rt' and 'choice_made'
            data = (out[0]*out[1]).reshape(n_samples, )
        else:        
            # concatenate 'rt' and 'choice_made'
            data = np.concatenate((out[0].T, out[1].T), axis=1).reshape(2*n_samples,) 
            
        X_train.append(data)    
        
    X_train = np.array(X_train)         
    # Concatenating a, v and w
    param = np.concatenate((a.reshape(-1, 1), v.reshape(-1, 1), w.reshape(-1, 1)), axis=1)
    
    return tf.convert_to_tensor(X_train, dtype=tf.float32), tf.convert_to_tensor(param, dtype=tf.float32)


def load_model_and_opt(n_inv_blocks, global_step):
    """Loads a GMM model given the number of invertible blocks."""
    
    # Create model
    model = DeepConditionalModel(inv_meta, n_inv_blocks, theta_dim, summary_net=None, permute=True)
    optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate)
    
    # Checkpoint model
    checkpoint = tf.train.Checkpoint(step=global_step, optimizer=optimizer, net=model)
    manager = tf.train.CheckpointManager(checkpoint, './checkpoints/levy_flexbound_constant_multiply{}'.format(n_inv_blocks), max_to_keep=2)
    checkpoint.restore(manager.latest_checkpoint)
    
    if manager.latest_checkpoint:
        print("Restored from {}".format(manager.latest_checkpoint))
        epoch_restore = manager.latest_checkpoint.split('-')[1]
#         print(epoch_restore)
    else:
        print("Initializing from scratch.")
        epoch_restore = 0
    
    return model, optimizer, manager

def train_model(n_inv_blocks):
    """
    Runs the Gausian Distribution
    """
    
    model, optimizer, manager = load_model_and_opt(n_inv_blocks, global_step)
    
    for ep in range(1, epochs+1):
        with tqdm(total=iterations_per_epoch, desc='Training epoch {}'.format(ep)) as p_bar:

            # Run training loop
            train_online_ml(model, optimizer, data_generator_ddm_flexbound, iterations_per_epoch, 
                            batch_size, p_bar=p_bar, clip_value=clip_value, global_step=global_step, 
                            transform=None, n_smooth=100)
            
            manager.save()


# Setting the various configurations
inv_meta = {
    'n_units': [128, 128, 128],
    'activation': 'elu',
    'w_decay': 0.0,
    'initializer': 'glorot_uniform'
}

n_inv = 10
theta_dim = 3
# params_names = [r'$\mu_{}$'.format(i+1) for i in range(theta_dim)]
global_step = tf.Variable(0, dtype=tf.int32)
batch_size = 64
epochs = 40
iterations_per_epoch = 100
n_samples_posterior = 2000
starter_learning_rate = 0.001
decay_steps = 1000
decay_rate = .99
clip_value = 5.
learning_rate = tf.train.exponential_decay(starter_learning_rate, global_step, 
                                           decay_steps, decay_rate, staircase=True)


train_model(n_inv)