"""Configure contact SMTP using a masked local prompt; never persist the password locally."""
import smtplib
import ssl
import certifi
import getpass
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog

from configure_azure import arm, RESOURCE


def configure(password):
    with smtplib.SMTP_SSL('mail.privateemail.com', 465,
                          context=ssl.create_default_context(cafile=certifi.where()), timeout=20) as client:
        client.login('support@pokerfill.com', password)
    settings = arm('POST', RESOURCE+'/listAppSettings', {})['properties']
    settings['POKERFILL_SMTP_PASSWORD'] = password
    arm('PUT', RESOURCE+'/config/appsettings', {'properties': settings})


def main():
    if '--terminal' in sys.argv:
        password = getpass.getpass('Mailbox SMTP password: ')
        try:
            configure(password)
            print('SMTP verified and Azure contact email configured.')
        except Exception as exc:
            print('Configuration failed:', type(exc).__name__)
            raise SystemExit(1)
        finally:
            password = None
        return
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    password = simpledialog.askstring('PokerFill contact email setup',
        'Enter the SMTP/app password for support@pokerfill.com.\n'
        'It will be checked with Namecheap and saved securely in Azure.\n'
        'Use the mailbox password, not your Namecheap account password.',
        show='*', parent=root)
    if not password:
        root.destroy()
        return
    try:
        configure(password)
    except Exception as exc:
        messagebox.showerror('PokerFill contact email setup',
            'Configuration did not complete ('+type(exc).__name__+'). Check the SMTP/app password and connection, then try again. '
            'No password has been printed or saved to a local file.', parent=root)
    else:
        messagebox.showinfo('PokerFill contact email setup',
            'SMTP login verified. The contact email password is now configured in Azure.', parent=root)
    finally:
        password = None
        root.destroy()


if __name__ == '__main__':
    main()
