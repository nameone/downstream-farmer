#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import print_function

import io
import json
import time

import requests
import heartbeat
from RandomIO import RandomIO
from datetime import datetime

from .utils import handle_json_response
from .exc import DownstreamError


class Contract(object):
    def __init__(self, hash, seed, size, challenge, expiration, tag):
        self.hash = hash
        self.seed = seed
        self.size = size
        self.challenge = challenge
        self.expiration = expiration
        self.tag = tag

heartbeat_types = {'SwPriv': heartbeat.SwPriv.SwPriv,
                   'Merkle': heartbeat.Merkle.Merkle}


class DownstreamClient(object):
    def __init__(self, address):
        self.address = address
        self.token = ''
        self.server = ''
        self.heartbeat = None
        self.contract = None

    def connect(self, url):
        """Connects to a downstream-node server.

        :param url: the node url, e.g. https://localhost:5000/
        """
        self.server = url.strip('/')
        url = '{0}/api/downstream/new/{1}'.format(self.server, self.address)

        resp = requests.get(url)
        r_json = handle_json_response(resp)

        for k in ['token', 'heartbeat', 'type']:
            if (k not in r_json):
                raise DownstreamError('Malformed response from server.')

        if r_json['type'] not in heartbeat_types.keys():
            raise DownstreamError('Unknown Heartbeat Type')

        self.token = r_json['token']
        self.heartbeat \
            = heartbeat_types[r_json['type']].fromdict(r_json['heartbeat'])

    def get_chunk(self):
        """Gets a chunk contract from the connected node
        """
        url = '{0}/api/downstream/chunk/{1}'.format(self.server, self.token)

        resp = requests.get(url)
        r_json = handle_json_response(resp)

        for k in ['file_hash', 'seed', 'size', 'challenge', 'tag']:
            if (k not in r_json):
                raise DownstreamError('Malformed response from server.')

        self.contract = Contract(
            r_json['file_hash'],
            r_json['seed'],
            r_json['size'],
            self.heartbeat.challenge_type().fromdict(r_json['challenge']),
            datetime.strptime(r_json['expiration'], '%Y-%m-%dT%H:%M:%S'),
            self.heartbeat.tag_type().fromdict(r_json['tag']))

    def get_challenge(self, block=True):
        """Gets a new challenge from the connected node.

        Checks that existing contract has expired before getting a new one
        :param block: if block is True, waits until the old challenge has
        expired before getting the new one.  Otherwise, if the old challenge
        has not expired, returns None
        :returns: the new contract
        """
        if (self.contract is None):
            raise DownstreamError('No contract to get a new challenge for.')

        time_til_expiration = self.contract.expiration - datetime.utcnow()
        if (time_til_expiration.total_seconds() > 0):
            if (block):
                print('Waiting {0} seconds until new challenge is available.'
                      .format(time_til_expiration.total_seconds()))
                # contract expiration is in the future...
                # wait til contract expiration
                time.sleep(time_til_expiration.total_seconds())
            else:
                return None

        # now contract should be expired, we can get a new challenge

        url = '{0}/api/downstream/challenge/{1}/{2}'.format(self.server,
                                                            self.token,
                                                            self.contract.hash)

        resp = requests.get(url)

        r_json = handle_json_response(resp)

        for k in ['challenge', 'expiration']:
            if (k not in r_json):
                raise DownstreamError('Malformed response from server.')

        self.contract.challenge \
            = self.heartbeat.challenge_type().fromdict(r_json['challenge'])
        self.contract.expiration \
            = datetime.strptime(r_json['expiration'], '%Y-%m-%dT%H:%M:%S')

        return self.contract

    def answer_challenge(self):
        """Answers the chunk contract for the connected node.
        """
        if (self.contract is None):
            raise DownstreamError('No contract to answer.')

        contract = self.contract

        url = '{0}/api/downstream/answer/{1}/{2}'.format(self.server,
                                                         self.token,
                                                         contract.hash)

        with io.BytesIO(RandomIO(contract.seed).read(contract.size)) as f:
            proof = self.heartbeat.prove(f, contract.challenge, contract.tag)

        data = {
            'proof': proof.todict()
        }
        headers = {
            'Content-Type': 'application/json'
        }

        resp = requests.post(url, data=json.dumps(data), headers=headers)
        r_json = handle_json_response(resp)

        if ('status' not in r_json):
            raise DownstreamError('Malformed response from server.')

        if (r_json['status'] != 'ok'):
            raise DownstreamError('Challenge response rejected.')
