#!/usr/bin/python3
import os
import sys
import logging
import smtplib
import base64
from getpass import getpass
import pickle
from requests import get, post
from email.message import EmailMessage


IP = None


def get_cwd():
    if os.name == 'nt':
        return os.path.dirname(os.path.realpath(__file__))
    os.chdir(os.path.dirname(sys.argv[0]))
    return os.getcwd()


logger = logging.getLogger('')
logger.setLevel(logging.INFO)
fh = logging.FileHandler(f'{get_cwd()}/ipchecker.log')
sh = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('[%(levelname)s]|%(asctime)s|%(message)s',
                               datefmt='%d %b %Y %H:%M:%S')
fh.setFormatter(formatter)
sh.setFormatter(formatter)
logger.addHandler(fh)
logger.addHandler(sh)


class User:
    def __init__(self, *args, **kwargs):
        if os.path.isfile(f"{get_cwd()}/user.pickle"):
            self.load_user()
        else:
            self.gmail_address = input("What's your email address?: ")
            self.gmail_password = base64.b64encode(getpass("What's your email password?: ").encode("utf-8"))
            self.DNS_username = input("What's your autogenerated DNS username?: ")
            self.DNS_password = input("What's your autogenerated DNS password?: ")
            self.domain = input("What's your domain (and subdomain: @.example.com / site.example.com)?: ")
            self.req_url = f'https://{self.DNS_username}:{self.DNS_password}@domains.google.com/nic/update?hostname={self.domain}&myip='
            self.save_user()

    def send_notification(self, type='success', error=None):
        msg = EmailMessage()
        if type == 'success':
            msg.set_content(f'IP for {self.domain} has changed! New IP: {IP}')
            msg['Subject'] = 'IP CHANGED SUCCESSFULLY!'
        elif type == 'error':
            msg.set_content(f'IP for {self.domain} has changed but the API call failed ({error})! New IP: {IP}')
            msg['Subject'] = 'IP CHANGE FAILED!'
        msg['From'] = self.gmail_address
        msg['To'] = self.gmail_address
        try:
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.ehlo()
            server.login(self.gmail_address, base64.b64decode(self.gmail_password).decode('utf-8'))
            server.send_message(msg)
            server.close()
        except Exception as e:
            logger.warning(f'Email notification not sent:{e}')

    def save_user(self):
        with open('user.pickle', 'wb') as pickle_file:
            pickle.dump(self, pickle_file)

    def load_user(self):
        with open('user.pickle', 'rb') as pickle_file:
            self.__dict__.update(pickle.load(pickle_file).__dict__)


class IpChanger:
    def __init__(self):
        global IP
        self.current_ip = get('https://api.ipify.org').text
        IP = self.current_ip
        self.user = User()
        self.first_run = False
        self.change = False
        self.old_ip = self.check_ip()
        if self.old_ip != self.current_ip:
            self.change_ip()
        else:
            logger.info(f'Current IP: {self.current_ip}')

    def check_ip(self):
        if os.path.isfile(f"{get_cwd()}/ip.txt"):
            with open(f'{get_cwd()}/ip.txt', 'r') as rf:
                line = rf.readlines()
                if not line:
                    self.first_run = True
                    return self.store_ip()
                elif line[0] == self.current_ip:
                    self.first_run = False
                    self.change = False
                    return self.current_ip
                else:
                    self.first_run = False
                    self.change = True
                    return self.store_ip()
        else:
            self.first_run = True
            return self.store_ip()

    def store_ip(self):
        with open(f'{get_cwd()}/ip.txt', 'w') as wf:
            if self.first_run:
                logger.info('recording first IP (no change to DNS)')
                wf.write(self.current_ip)
            elif self.change:
                logger.info('changing IP address...')
                wf.write(self.current_ip)
                self.change_ip()
        return self.current_ip

    def change_ip(self):
        try:
            req = post(f'{self.user.req_url}{self.current_ip}')
            logger.info(f"domains.google api response: {req.content.decode('utf-8')}")
            self.user.send_notification()
        except Exception as e:
            logger.warning(f'API call failed: {e}')
            self.user.send_notification('error', e)


if __name__ == "__main__":
    IpChanger()
