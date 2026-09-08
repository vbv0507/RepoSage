import nodemailer from 'nodemailer';
import dotenv from 'dotenv';
dotenv.config();

let transporter = null;
let isEthereal = false;

async function getTransporter() {
  if (transporter) return transporter;

  const emailUser = process.env.EMAIL_USER || process.env.SMTP_USER;
  const emailPass = (process.env.EMAIL_PASS || process.env.SMTP_PASS || '').replace(/\s+/g, '');
  const host = process.env.SMTP_HOST;
  const port = process.env.SMTP_PORT || 587;

  if (emailUser && emailPass) {
    if (emailUser.endsWith('@gmail.com')) {
      console.log(`[Mailer] 📧 Configured Gmail service for: ${emailUser}`);
      transporter = nodemailer.createTransport({
        service: 'gmail',
        auth: {
          user: emailUser,
          pass: emailPass
        }
      });
    } else {
      console.log(`[Mailer] 📧 Configured production SMTP for ${emailUser} via ${host || 'localhost'}:${port}`);
      transporter = nodemailer.createTransport({
        host: host || 'localhost',
        port: Number(port),
        secure: port == 465,
        auth: {
          user: emailUser,
          pass: emailPass
        }
      });
    }
    isEthereal = false;
  } else {
    console.log('[Mailer] 📧 No SMTP credentials configured. Initializing Ethereal test inbox for development...');
    try {
      const testAccount = await nodemailer.createTestAccount();
      transporter = nodemailer.createTransport({
        host: 'smtp.ethereal.email',
        port: 587,
        secure: false,
        auth: {
          user: testAccount.user,
          pass: testAccount.pass
        }
      });
      isEthereal = true;
      console.log(`[Mailer] 🧪 Ethereal test account ready: ${testAccount.user}`);
    } catch (e) {
      console.warn('[Mailer] Could not connect to Ethereal, falling back to simulated mailer:', e.message);
      // Fallback simulated transporter
      transporter = {
        sendMail: async (opts) => ({
          messageId: `sim_${Date.now()}`,
          simulated: true
        })
      };
      isEthereal = true;
    }
  }

  return transporter;
}

/**
 * Send an architecture blueprint PDF via email
 */
export async function sendTutorialEmail({ toEmail, repoName, pdfBuffer }) {
  if (!toEmail) throw new Error('Recipient email address is required.');

  const mailer = await getTransporter();
  const filename = `${(repoName || 'architecture').replace(/[^a-zA-Z0-9_-]/g, '_')}_Blueprint.pdf`;
  const fromAddress = process.env.FROM_EMAIL || '"RepoSage Architecture AI" <copilot@reposage.dev>';

  const html = `
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e4e4e7; border-radius: 8px; overflow: hidden;">
      <div style="background-color: #09090b; padding: 24px; color: #ffffff;">
        <span style="font-size: 11px; font-weight: 700; color: #3b82f6; text-transform: uppercase; letter-spacing: 0.05em;">RepoSage Architecture Intelligence</span>
        <h1 style="font-size: 20px; font-weight: 700; margin: 8px 0 0 0; color: #ffffff;">Engineering Blueprint: ${repoName || 'Codebase'}</h1>
      </div>
      <div style="padding: 24px; color: #27272a; line-height: 1.6; font-size: 14px;">
        <p>Hello,</p>
        <p>Your requested <strong>Architecture Blueprint & Engineering Documentation</strong> for <strong>${repoName || 'the repository'}</strong> has been autonomously generated and is attached to this email as a PDF.</p>
        
        <div style="background-color: #f4f4f5; border-left: 4px solid #3b82f6; padding: 14px 16px; margin: 20px 0; border-radius: 0 4px 4px 0;">
          <strong style="color: #09090b; font-size: 13px;">Included in this Blueprint:</strong>
          <ul style="margin: 8px 0 0 0; padding-left: 20px; font-size: 13px; color: #52525b;">
            <li>System Overview & Component Topology (C4 Diagram)</li>
            <li>End-to-End Request & Data Flow (Sequence Diagram)</li>
            <li>Database Entities & Schema Relationships (ERD)</li>
            <li>Security, Authentication & Trust Boundaries</li>
            <li>Developer Onboarding & Feature Extension Guide</li>
          </ul>
        </div>

        <p style="font-size: 12px; color: #71717a; margin-top: 24px; border-top: 1px solid #e4e4e7; padding-top: 16px;">
          Generated autonomously by <strong>RepoSage</strong> • Codebase Architecture Copilot
        </p>
      </div>
    </div>
  `;

  const mailOptions = {
    from: fromAddress,
    to: toEmail,
    subject: `RepoSage Architecture Blueprint: ${repoName || 'Codebase'}`,
    html,
    attachments: [
      {
        filename,
        content: pdfBuffer,
        contentType: 'application/pdf'
      }
    ]
  };

  const info = await mailer.sendMail(mailOptions);
  let previewUrl = null;

  if (isEthereal && nodemailer.getTestMessageUrl) {
    previewUrl = nodemailer.getTestMessageUrl(info);
    if (previewUrl) {
      console.log(`[Mailer] 🌐 Email sent! Ethereal Preview URL: ${previewUrl}`);
    }
  }

  return {
    success: true,
    messageId: info.messageId,
    previewUrl,
    isEthereal
  };
}
