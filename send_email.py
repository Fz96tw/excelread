import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import markdown

def send_markdown_email(subject: str, from_address: str, to_address: str, data: str):
    """
    Send an email with Markdown content using Gmail + App Password.

    Parameters:
        to_address (str): The recipient's email address.
        data (str): The message body in Markdown.
    """

    # Gmail SMTP settings
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    smtp_user = "fz96tw@gmail.com"                # your Gmail address
    smtp_password = "rsbz vxky fiwa efnbp"        # your 16-char app password

    # Convert Markdown to HTML
    html_content = markdown.markdown(data)

    # Create a multipart message (plain + HTML)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address

    # Attach plain-text (raw markdown) and HTML parts
    part1 = MIMEText(data, "plain")
    part2 = MIMEText(html_content, "html")

    msg.attach(part1)
    msg.attach(part2)

    # Send email
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()                # start TLS encryption
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
