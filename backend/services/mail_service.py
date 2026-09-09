import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import Dict, Any

logger = logging.getLogger("mail_service")

async def send_tutorial_email(to_email: str, repo_name: str, pdf_bytes: bytes) -> Dict[str, Any]:
    email_user = os.getenv("EMAIL_USER") or os.getenv("SMTP_USER")
    email_pass = (os.getenv("EMAIL_PASS") or os.getenv("SMTP_PASS") or "").replace(" ", "")
    smtp_host = os.getenv("SMTP_HOST") or ("smtp.gmail.com" if (email_user and email_user.endswith("@gmail.com")) else "localhost")
    smtp_port = int(os.getenv("SMTP_PORT") or (465 if smtp_host == "smtp.gmail.com" else 587))

    if not email_user or not email_pass:
        logger.info(f"[Mailer] 📧 No SMTP credentials configured. Simulating delivery for {to_email}...")
        return {
            "delivered": True,
            "simulated": True,
            "messageId": f"sim_{os.urandom(6).hex()}",
            "previewUrl": None,
            "isEthereal": True
        }

    try:
        msg = MIMEMultipart()
        msg["From"] = f"RepoSage AI <{email_user}>"
        msg["To"] = to_email
        msg["Subject"] = f"📘 Architectural Blueprint: {repo_name} (Engineering Textbook)"

        body = (
            f"Hello,\n\n"
            f"Your comprehensive 10-chapter architectural blueprint and engineering textbook for {repo_name} "
            f"has been compiled by RepoSage Principal Architect AI.\n\n"
            f"Attached is your publication-grade PDF containing system topologies, sequence flows, database ERDs, "
            f"background queues, and developer extension recipes.\n\n"
            f"Best regards,\n"
            f"RepoSage AI Team"
        )
        msg.attach(MIMEText(body, "plain"))

        # Attach PDF
        pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        filename = f"{repo_name.replace(' ', '_')}_architecture_blueprint.pdf"
        pdf_attachment.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(pdf_attachment)

        # Send via SMTP
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=20)
            server.starttls()

        server.login(email_user, email_pass)
        server.send_message(msg)
        server.quit()

        logger.info(f"[Mailer] 📧 Successfully dispatched architectural PDF to {to_email}")
        return {
            "delivered": True,
            "simulated": False,
            "messageId": f"smtp_{os.urandom(8).hex()}",
            "previewUrl": None,
            "isEthereal": False
        }
    except Exception as e:
        logger.error(f"[Mailer] ❌ Failed to dispatch email via SMTP: {e}")
        raise e
