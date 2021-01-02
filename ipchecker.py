#!/usr/bin/python3
import base64
import getopt
import logging
import os
import pickle
import smtplib
import sys
from email.message import EmailMessage
from getpass import getpass

from requests import get, post
from requests.exceptions import ConnectionError


def get_cwd():
    """Change &/ return working directory depending on OS: for absolute file paths
    Cron jobs will have '/' as their working dir by default."""

    if os.name == 'nt':
        return os.path.dirname(os.path.realpath(__file__))
    os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))
    return os.getcwd()


logger = logging.getLogger('')
logger.setLevel(logging.INFO)
fh = logging.FileHandler(f'{get_cwd()}/ipchecker.log')
sh = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('[%(levelname)s]|%(asctime)s|%(message)s',
                              datefmt='%d %b %Y %H:%M:%S')
fh.setFormatter(formatter)
sh.setFormatter(formatter)
logger.addHandler(sh)
logger.addHandler(fh)


class User:

    BASE_URL = '@domains.google.com/nic/update?hostname='

    def __init__(self):

        """Create user instance and save it for future changes to API and for email notifications,
        or load previous user profile"""

        if os.path.isfile(f".user.pickle"):
            self.load_user()
        else:
            self.notifications = 'Y'
            self.domain, self.DNS_username, self.DNS_password, self.req_url = self.set_credentials()
            self.gmail_address, self.gmail_password = self.set_email()
            self.save_user()
            logging.info('New user created. (See `python3 ipchecker.py --help` for help changing/removing the user)')

    def set_credentials(self, update=False):

        """Take/return inputs for Google Domains credentials"""

        self.domain = input("What's your domain? (example.com / subdomain.example.com): ")
        self.DNS_username = input("What's your autogenerated DNS username?: ")
        self.DNS_password = input("What's your autogenerated DNS password?: ")
        self.req_url = f'https://{self.DNS_username}:{self.DNS_password}{self.BASE_URL}{self.domain}&myip='
        if update:
            self.save_user()
        return self.domain, self.DNS_username, self.DNS_password, self.req_url

    def set_email(self):

        """Take/return inputs for Gmail credentials if notifications enabled"""

        self.notifications = input("Enable email notifications? Y/all(default); 1/errors only; n/no: ").lower()
        if self.notifications != 'n':
            self.gmail_address = input("What's your email address?: ")
            self.gmail_password = base64.b64encode(getpass("What's your email password?: ").encode("utf-8"))
            return self.gmail_address, self.gmail_password
        else:
            return None, None

    def send_notification(self, ip, msg_type='success', error=None):

        """Notify user via email if IP change is made successfully or if API call fails."""

        if self.notifications != 'n':
            msg = EmailMessage()
            if msg_type == 'success' and self.notifications != 'n' and self.notifications != '1':
                msg.set_content(f'IP for {self.domain} has changed! New IP: {ip}')
                msg['Subject'] = 'IP CHANGED SUCCESSFULLY!'
            elif msg_type == 'error' and self.notifications != 'n':
                msg.set_content(f'IP for {self.domain} has changed but the API call failed ({error})! New IP: {ip}')
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
        with open(f'.user.pickle', 'wb') as pickle_file:
            pickle.dump(self, pickle_file)

    def load_user(self, pickle_file=f'.user.pickle'):
        with open(pickle_file, 'rb') as pickle_file:
            self.__dict__.update(pickle.load(pickle_file).__dict__)

    @staticmethod
    def delete_user():
        os.remove(f'{get_cwd()}/.user.pickle')


class IPChanger:

    def __init__(self, argv):

        """Check for command line arguments, load User instance,
        check previous IP address against current external IP, and change if different."""

        opts = []
        try:
            opts, args = getopt.getopt(argv, "cdehu:", ["credentials", "delete_user", "email", "help", "user_pickle="])
            self.current_ip = get('https://api.ipify.org').text

        except getopt.GetoptError:
            print('ipchecker.py -h --help')
            sys.exit(2)

        except ConnectionError:
            logger.warning('Connection Error')
            sys.exit(1)

        finally:
            self.user = User()
            if opts:
                for opt, arg in opts:
                    if opt == '-h':
                        print(
                            """                    
        ipchecker.py                        || run the script normally without arguments
        ipchecker.py -c --credentials       || change API credentials
        ipchecker.py -e --email             || change email notification settings
        ipchecker.py -d --delete_user       || delete current user profile
        ipchecker.py -u new_user.pickle     || load user from pickle_file (or `--user_pickle new_user.pickle`)
                                               **this will overwrite your current user profile without warning!**
                            """
                        )

                    elif opt in ("-c", "--credentials"):
                        self.user.set_credentials(update=True)
                        self.domains_api_call()
                        logger.info('***API credentials changed***')

                    elif opt in ("-d", "--delete"):
                        self.user.delete_user()
                        logger.info('***User deleted***')
                        print('>>>Run the script without arguments to create a new user.')

                    elif opt in ("-e", "--email"):
                        self.user.set_email()
                        self.user.save_user()
                        logger.info('***Notification settings changed***')

                    elif opt in ("-u", "--user_pickle"):
                        try:
                            self.user.load_user(pickle_file=arg)
                            self.user.save_user()
                            logger.info('***User changed***')
                        except Exception as e:
                            logger.warning(e)
                            sys.exit(2)
                    sys.exit()

            try:
                if self.user.previous_ip == self.current_ip:
                    logger.info(f'Current IP: {self.user.previous_ip} (no change)')
                else:
                    self.user.previous_ip = self.current_ip
                    self.domains_api_call()
                    logger.info(f'Newly recorded IP: {self.user.previous_ip}')
                    self.user.save_user()

            except AttributeError:
                setattr(self.user, 'previous_ip', self.current_ip)
                self.user.save_user()
                self.domains_api_call()

            finally:
                sys.exit()

    def domains_api_call(self):

        """Attempt to change the Dynamic DNS rules via the Google Domains API and handle response codes"""

        try:
            req = post(f'{self.user.req_url}{self.current_ip}')
            response = req.content.decode('utf-8')
            logger.info(f"Google Domains API response: {response}")

            # Successful request:
            if response[:4] == 'good' or response[:5] == 'nochg':
                self.user.send_notification(self.current_ip)

            # Unsuccessful requests:
            elif response == 'nohost' or response == 'notfqdn':
                msg = "The hostname does not exist, is not a fully qualified domain" \
                      " or does not have Dynamic DNS enabled. The script will not be " \
                      "able to run until you fix this. See https://support.google.com/domains/answer/6147083?hl=en-CA" \
                      " for API documentation"
                logger.warning(msg)
                if input("Recreate the API profile? (Y/n):").lower() != 'n':
                    self.user.set_credentials(update=True)
                    self.domains_api_call()
                else:
                    self.user.send_notification(self.current_ip, 'error', msg)
            else:
                logger.warning("Could not authenticate with these credentials")
                if input("Recreate the API profile? (Y/n):").lower() != 'n':
                    self.user.set_credentials(update=True)
                    self.domains_api_call()
                else:
                    self.user.delete_user()
                    logger.warning('API authentication failed, user profile deleted')
                    sys.exit(2)

        except Exception as e:  # Non-API related errors
            logger.warning(f'API call failed: {e}')
            self.user.send_notification(self.current_ip, 'error', e)


if __name__ == "__main__":
    IPChanger(sys.argv[1:])
