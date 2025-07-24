import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_personalized_email(sender_email, sender_password, recipient_email, subject, body):
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipient_email, msg.as_string())
        print(f"[INFO] Email sent to {recipient_email}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send email to {recipient_email}: {e}")
        return False
