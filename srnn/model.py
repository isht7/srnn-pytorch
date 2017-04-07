'''
The structural RNN model
introduced in https://arxiv.org/abs/1511.05298

Author : Anirudh Vemula
Date : 16th March 2017
'''

import torch.nn as nn
from torch.autograd import Variable
import torch


class HumanNodeRNN(nn.Module):
    '''
    Class representing human Node RNNs in the st-graph
    '''
    def __init__(self, args, infer=False):
        super(HumanNodeRNN, self).__init__()

        self.args = args
        self.infer = infer

        self.rnn_size = args.human_node_rnn_size
        self.output_size = args.human_node_output_size
        self.embedding_size = args.human_node_embedding_size
        self.input_size = args.human_node_input_size

        self.encoder_linear = nn.Linear(self.input_size, self.embedding_size)
        self.encoder_relu = nn.ReLU()

        self.hidden_encoder_linear = nn.Linear(args.human_human_edge_rnn_size*2, self.embedding_size)
        self.hidden_encoder_relu = nn.ReLU()

        self.cell = nn.GRUCell(2*self.embedding_size, self.rnn_size)

        # self.lr = args.learning_rate

        self.decoder_linear = nn.Linear(self.rnn_size, self.output_size)

    def init_weights(self):
        self.encoder_linear.weight.data.normal_(0, 0.1)
        self.encoder_linear.bias.data.fill_(0)

        self.hidden_encoder_linear.weight.data.normal_(0, 0.1)
        self.hidden_encoder_linear.bias.data.fill_(0)

        self.decoder_linear.weight.data.normal_(0, 0.1)
        self.decoder_linear.bias.data.fill_(0)

    def forward(self, pos, h_other, h):
        # Encode the input position
        encoded_input = self.encoder_linear(pos)
        encoded_input = self.encoder_relu(encoded_input)

        # Encode the input hidden states
        encoded_hidden = self.hidden_encoder_linear(h_other)
        encoded_hidden = self.hidden_encoder_relu(encoded_hidden)

        # Concat both the embeddings
        concat_encoded = torch.cat((encoded_input, encoded_hidden), 1)

        # One-step of GRU
        h_new = self.cell(concat_encoded, h)

        # Decode hidden state
        out = self.decoder_linear(h_new)

        return out, h_new


class HumanHumanEdgeRNN(nn.Module):
    '''
    Class representing the Human-Human Edge RNN in the s-t graph
    '''
    def __init__(self, args, infer=False):
        super(HumanHumanEdgeRNN, self).__init__()

        self.args = args
        self.infer = infer

        self.rnn_size = args.human_human_edge_rnn_size
        self.embedding_size = args.human_human_edge_embedding_size
        self.input_size = args.human_human_edge_input_size

        self.encoder_linear = nn.Linear(self.input_size, self.embedding_size)
        self.encoder_relu = nn.ReLU()

        # self.hidden_encoder_linear = nn.Linear(self.input_size, self.embedding_size)
        # self.hidden_encoder_relu = nn.ReLU()

        self.cell = nn.GRUCell(self.embedding_size, self.rnn_size)

    def init_weights(self):

        self.encoder_linear.weight.data.normal_(0, 0.1)
        self.encoder_linear.bias.data.fill_(0)

        # self.hidden_encoder_linear.weight.data.normal_(0, 0.1)
        # self.hidden_encoder_linear.bias.data.fill_(0)

    def forward(self, inp, h):

        # Encode the input position
        encoded_input = self.encoder_linear(inp)
        encoded_input = self.encoder_relu(encoded_input)

        # Encode the input hidden states
        # encoded_hidden = self.hidden_encoder_linear(h_other)
        # encoded_hidden = self.hidden_encoder_relu(encoded_hidden)

        # Concat both the embeddings
        # concat_encoded = torch.cat((encoded_input, encoded_hidden), dimension=0)

        # One-step of GRU
        h_new = self.cell(encoded_input, h)

        return h_new


class SRNN(nn.Module):
    '''
    Class representing the SRNN model
    '''
    def __init__(self, args, infer=False):
        super(SRNN, self).__init__()

        self.args = args
        self.infer = infer

        if self.infer:
            self.seq_length = 1
        else:
            self.seq_length = args.seq_length
        self.human_node_rnn_size = args.human_node_rnn_size
        self.human_human_edge_rnn_size = args.human_human_edge_rnn_size
        self.output_size = args.human_node_output_size

        # Initialize the Node and Edge RNNs
        self.humanNodeRNN = HumanNodeRNN(args, infer)
        self.humanhumanEdgeRNN_spatial = HumanHumanEdgeRNN(args, infer)
        self.humanhumanEdgeRNN_temporal = HumanHumanEdgeRNN(args, infer)

        # Initialize the weights of the Node and Edge RNNs
        self.humanNodeRNN.init_weights()
        self.humanhumanEdgeRNN_spatial.init_weights()
        self.humanhumanEdgeRNN_temporal.init_weights()

    def forward(self, nodes, edges, nodesPresent, edgesPresent, hidden_states_node_RNNs, hidden_states_edge_RNNs):
        '''
        Parameters
        ==========

        nodes : A tensor of shape seq_length x numNodes x 1 x 2
        Each row contains (x, y)

        edges : A tensor of shape seq_length x numNodes x numNodes x 1 x 2
        Each row contains the vector representing the edge
        If edge doesn't exist, then the row contains zeros

        nodesPresent : A list of lists, of size seq_length
        Each list contains the nodeIDs that are present in the frame

        edgesPresent : A list of lists, of size seq_length
        Each list contains tuples of nodeIDs that have edges in the frame

        hidden_states_node_RNNs : A tensor of size numNodes x 1 x node_rnn_size
        Contains hidden states of the node RNNs

        hidden_states_edge_RNNs : A tensor of size numNodes x numNodes x 1 x edge_rnn_size
        Contains hidden states of the edge RNNs

        Returns
        =======

        outputs : A tensor of shape seq_length x numNodes x 1 x 5
        Contains the predictions for next time-step

        hidden_states_node_RNNs

        hidden_states_edge_RNNs
        '''
        # Get number of nodes
        numNodes = nodes.size()[1]

        # Initialize output array
        outputs = Variable(torch.zeros(self.seq_length * numNodes, self.output_size)).cuda()
        # outputs_assign = outputs.view(self.seq_length * numNodes, self.output_size)

        for framenum in range(self.seq_length):
            edgeIDs = edgesPresent[framenum]
            temporal_edges = [x for x in edgeIDs if x[0] == x[1]]
            spatial_edges = [x for x in edgeIDs if x[0] != x[1]]

            hidden_states_nodes_from_edges_temporal = Variable(torch.zeros(numNodes, self.human_human_edge_rnn_size).cuda())
            hidden_states_nodes_from_edges_spatial = Variable(torch.zeros(numNodes, self.human_human_edge_rnn_size).cuda())

            if len(edgeIDs) != 0:

                if len(temporal_edges) != 0:

                    list_of_temporal_edges = Variable(torch.LongTensor([x[0]*x[0] for x in edgeIDs if x[0] == x[1]]).cuda())
                    list_of_temporal_nodes = torch.LongTensor([x[0] for x in edgeIDs if x[0] == x[1]]).cuda()

                    edges_temporal_start_end = torch.index_select(edges[framenum], 0, list_of_temporal_edges)
                    hidden_temporal_start_end = torch.index_select(hidden_states_edge_RNNs, 0, list_of_temporal_edges)

                    h_temporal = self.humanhumanEdgeRNN_temporal(edges_temporal_start_end, hidden_temporal_start_end)

                    hidden_states_edge_RNNs[list_of_temporal_edges.data] = h_temporal
                    hidden_states_nodes_from_edges_temporal[list_of_temporal_nodes] = h_temporal

                if len(spatial_edges) != 0:

                    list_of_spatial_edges = Variable(torch.LongTensor([x[0]*(numNodes) + x[1] for x in edgeIDs if x[0] != x[1]]).cuda())
                    list_of_spatial_nodes = [x[0] for x in edgeIDs if x[0] != x[1]]

                    edges_spatial_start_end = torch.index_select(edges[framenum], 0, list_of_spatial_edges)
                    hidden_spatial_start_end = torch.index_select(hidden_states_edge_RNNs, 0, list_of_spatial_edges)

                    h_spatial = self.humanhumanEdgeRNN_spatial(edges_spatial_start_end, hidden_spatial_start_end)

                    hidden_states_edge_RNNs[list_of_spatial_edges.data] = h_spatial
                    for i, node in enumerate(list_of_spatial_nodes):
                        hidden_states_nodes_from_edges_spatial[node] = hidden_states_nodes_from_edges_spatial[node] + h_spatial[i]

            nodeIDs = nodesPresent[framenum]

            if len(nodeIDs) != 0:

                list_of_nodes = Variable(torch.LongTensor(nodeIDs).cuda())

                nodes_current = torch.index_select(nodes[framenum], 0, list_of_nodes)

                hidden_nodes_current = torch.index_select(hidden_states_node_RNNs, 0, list_of_nodes)

                hidden_other_current = torch.cat((hidden_states_nodes_from_edges_temporal[list_of_nodes.data],
                                                  hidden_states_nodes_from_edges_spatial[list_of_nodes.data]), 1)

                outputs[framenum * list_of_nodes.data], h_nodes = self.humanNodeRNN(nodes_current, hidden_other_current, hidden_nodes_current)
                hidden_states_node_RNNs[list_of_nodes.data] = h_nodes

        outputs_return = Variable(torch.zeros(self.seq_length, numNodes, self.output_size).cuda())
        for framenum in range(self.seq_length):
            for node in range(numNodes):
                outputs_return[framenum, node, :] = outputs[framenum*node, :]

        return outputs_return, hidden_states_node_RNNs, hidden_states_edge_RNNs
