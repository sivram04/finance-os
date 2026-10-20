# Privacy policy

_Last updated: 20 October 2026_

Finance OS is a portfolio demo. It contains **no real company or personal financial data**: Echo Labs and every
customer, employee, vendor and figure in it are simulated. This page explains what the public demo
(https://finance-os-905768726552.us-central1.run.app) handles when you use it.

## What you can see without giving anything
You can browse every page without an account, sign-in, email address or payment. The demo sets **no advertising or
tracking cookies** and uses no third-party analytics.

## What is stored in your browser
The site uses your browser's local storage, only on your device, for conveniences:
- whether you have seen the guided tour;
- whether the assistant panel is open or closed;
- your theme (light or dark) and the last conversation you had, so it reopens after a reload.

You can clear these at any time by clearing the site's data in your browser.

## What is sent to the server
- **Assistant questions.** Text you type into the assistant is sent to the demo's server and to **Google Vertex AI
  (Gemini)** to produce an answer. Conversations are kept in the demo server's temporary storage, which is reset
  whenever the server restarts (typically daily or when idle). **Do not type personal or confidential information.**
- **Uploaded documents.** Files you drop into the assistant (for example a vendor bill) are read to extract their
  fields and checked against the simulated ledger. They are kept in the same temporary storage and are not shared.
  Please upload only sample or dummy documents.
- **Approvals.** Approving or rejecting a card changes only the demo's simulated state.

## Logs
Like any web service, the hosting platform (**Google Cloud Run**) records standard request logs: time, page or API
path, response status, and technical details such as IP address and browser type. These are used only to keep the
demo running and to diagnose errors, and are retained under Google Cloud's default log retention (about 30 days).

## Processors
- **Google Cloud** (hosting, storage, logs) and **Google Vertex AI** (assistant answers), under Google Cloud's terms
  and data-processing commitments. Google does not use Vertex AI customer prompts to train its models.

## Your choices
Do not enter personal data. If you believe you have sent personal information through the demo and want it removed,
open an issue on the GitHub repository (without including the information itself), and it will be handled promptly.

## Changes
This policy may change as the demo changes; the date at the top shows the latest version.
