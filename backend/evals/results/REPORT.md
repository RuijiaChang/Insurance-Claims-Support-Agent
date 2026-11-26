# Live-model evaluation report

Run: 2026-11-26T22:16:22.887265+00:00
Provider: openai; model: gpt-4.1-mini; demo date: 2026-03-05.

Real model calls; consent polls use the same deterministic bundle as the API. LLM errors fail a scenario even if fallback reaches the expected state. Guard violations (including email polish), leaks and unsafe template fallbacks fail.

| Scenario | Result | Final phase | Leaks | Guard violations | LLM errors | p50 (s) | p95 (s) |
|---|---|---|---:|---:|---:|---:|---:|
| angry | PASS | VERIFY_ID | 0 | 0 | 0 | 2.82 | 3.55 |
| ava_no_claims | PASS | RESOLVE_INTENT | 0 | 0 | 0 | 2.59 | 2.59 |
| david_default | PASS | PROCESS_CASE | 0 | 0 | 0 | 2.53 | 2.84 |
| david_timeout | PASS | HANDOFF | 0 | 0 | 0 | 2.82 | 2.82 |
| margaret | PASS | CLOSED | 0 | 0 | 0 | 2.25 | 2.86 |
| off_topic | PASS | HANDOFF | 0 | 0 | 0 | 2.34 | 3.17 |
| switch_case | PASS | CLOSED | 0 | 0 | 0 | 2.31 | 2.70 |
| yawen_alias | PASS | RESOLVE_INTENT | 0 | 0 | 0 | 2.00 | 2.00 |

## Conversation evidence

### angry

**Turn 1 — VERIFY_ID / COLLECTING**

Thanks for sharing your name, Margaret. To verify your identity, please provide two more details from date of birth, phone number, email address, or the last four digits of your SSN.

**Turn 2 — VERIFY_ID / COLLECTING**

I understand how frustrating it is to repeat your information when you just want answers about your claim. We verify identity to protect your personal and claim details from unauthorized access. I noted you said your claim was denied, and I want to help you with that as soon as we confirm your identity. Please provide two more details like your date of birth, phone number, email, or last four digits of your SSN.

### ava_no_claims

**Turn 1 — RESOLVE_INTENT / NONE**

Thank you for verifying your identity. I have checked your account, and there are no claims on your policy at this time. Is there anything else I can assist you with today?

### david_default

**Turn 1 — VERIFY_ID / CONSENT_PENDING**

A consent request has been sent to the policyholder's phone on file at ***-***-**36. Once she approves it, I can continue helping you.

**Turn 2 — VERIFY_ID / CONSENT_PENDING**



**Turn 3 — RESOLVE_INTENT / AWAITING_CHOICE**

The policyholder has approved — I can now help you with their claims. Which claim would you like help with? You have: 1) healthcare claim from Jan 12, 2026 (denied); 2) healthcare claim from Jan 28, 2025 (closed); 3) dental claim from Nov 3, 2025 (closed); 4) auto claim from Feb 28, 2026 (open).

**Turn 4 — PROCESS_CASE / ACTIVE**

I've pulled up the healthcare claim from January 12, 2026, which was denied because the pathology report and the treating provider's office note were missing. To move forward, you can submit these documents through the member portal or claim upload link, ensuring they are complete and legible. Once we receive and can read these files, the claim will go back into review, which may take another review cycle before the status updates. Is there anything else you'd like to know about this claim?

### david_timeout

**Turn 1 — VERIFY_ID / CONSENT_PENDING**

A consent request has been sent to the policyholder's phone on file ending in 36. Once she approves it, I can continue helping you with the claims. Let me know if there's anything else you'd like to ask while waiting.

**Turn 2 — VERIFY_ID / CONSENT_PENDING**



**Turn 3 — VERIFY_ID / CONSENT_PENDING**



**Turn 4 — VERIFY_ID / CONSENT_PENDING**



**Turn 5 — VERIFY_ID / CONSENT_PENDING**



**Turn 6 — VERIFY_ID / CONSENT_EXPIRED**

The consent request expired before the policyholder approved it. I can resend it once, connect you with a representative, or we can end here.

**Turn 7 — HANDOFF / NONE**

I have passed your conversation to a representative who will follow up with you under ticket HT-794a6f. They will assist you further from here.

### margaret

**Turn 1 — PROCESS_CASE / ACTIVE**

Thank you for verifying your identity. I have your healthcare claim from January 12, 2026, here, which was denied. The claim was denied because the pathology report and the treating provider's office note were missing from the review file. Is there anything else you would like to know about this claim?

**Turn 2 — PROCESS_CASE / ACTIVE**

You need to send the pathology report and the office note. The pathology report should include patient name, specimen details, testing date, and clinician or lab signature if available. The office note should show patient name, visit date, assessment, and treatment or follow-up recommendation. The best way to submit these is through the member portal or claim upload link; if that's not available, support can help arrange fax or mail submission. Is there anything else I can help with on this claim?

**Turn 3 — PROCESS_CASE / ACTIVE**

For your claim CL-2048, please submit the pathology report and the office note within a week. Is there anything else I can assist you with regarding this claim?

**Turn 4 — POST_PROCESS / OFFER**

I can email a summary of our conversation to m*****@email.com if you'd like, or you can skip that. Would you like me to send it?

**Turn 5 — POST_PROCESS / PREVIEW**

Here's a summary of our conversation for your reference:

Subject: Summary of your claims support conversation

What we discussed:
- We talked about your healthcare claim from January 12, 2026, which was denied because the pathology report and the treating provider's office note were missing.

Claim status / outcome:
- CL-2048 — healthcare claim from Jan 12, 2026 (denied)
  Status: denied — Healthcare claim denied due to missing pathology report and office note
  Denial reason: the review file did not include the pathology report and the treating provider office note
  Expected reimbursement: $0.00
  Allowed maximum: $1,450.00
  Amount paid: $0.00

Next steps:
- CL-2048 — healthcare claim from Jan 12, 2026 (denied)
  Submit the pathology report and the office note
  Appeal deadline: 2026-03-18
  For claim CL-2048, the best starting point is usually the member portal or the claim upload link so the pathology report and the office note stay attached to the file. If online upload is not available, support can help arrange fax or mail handling.
  For claim CL-2048, please submit the pathology report and the office note within a week.

How to reach us:
- Reply to this email or call the number on your insurance card to reach claims support.

Would you like me to send this summary to your email now?

**Turn 6 — CLOSED / NONE**

I have sent the summary of our conversation to your email at m*****@email.com. Thank you for reaching out, and take care!

### off_topic

**Turn 1 — VERIFY_ID / COLLECTING**

I can only assist with insurance claims and policy questions. To continue, please provide any three of these identity details: full name, date of birth, phone number, email, or the last four digits of your SSN or national ID.

**Turn 2 — VERIFY_ID / COLLECTING**

I’m here to help with insurance claims and policy questions only. Please provide any three of these identity details so I can assist you: full name, date of birth, phone number, email, or the last four digits of your SSN or national ID.

**Turn 3 — VERIFY_ID / COLLECTING**

I can only help with insurance claims and policy questions. If you'd like, I can connect you with a representative who might assist further. Meanwhile, please provide any three of these identity details: full name, date of birth, phone number, email, or the last four digits of your SSN or national ID.

**Turn 4 — HANDOFF / NONE**

I’m connecting you now with a representative who will follow up on your request.

### switch_case

**Turn 1 — PROCESS_CASE / ACTIVE**

Thank you for verifying your identity. I've pulled up your healthcare claim from January 12, 2026, which was denied. The claim was denied because the review file did not include the pathology report and the treating provider office note. Once you submit these missing documents, the claim will go back into review, but it may need another review cycle before the status changes. Is there anything else you would like to know about this claim?

**Turn 2 — PROCESS_CASE / ACTIVE**

I have your open auto claim from February 28, 2026, in progress. The expected reimbursement amount is $3,200.00, with a maximum allowed amount of $3,500.00, but no payment has been made yet. Is there anything else you want to know about this auto claim?

**Turn 3 — POST_PROCESS / OFFER**

I can email you a summary of our conversation at m*****@email.com if you'd like. Would you like me to send it?

**Turn 4 — POST_PROCESS / PREVIEW**

Here's a summary draft of our conversation for your review:

Subject: Summary of your claims support conversation

What we discussed:
- We talked about your healthcare claim from January 12, 2026, which was denied because the pathology report and office note were missing, and your auto claim from February 28, 2026, which is still open.

Claim status / outcome:
- CL-2048 — healthcare claim from Jan 12, 2026 (denied)
  Status: denied — Healthcare claim denied due to missing pathology report and office note
  Denial reason: the review file did not include the pathology report and the treating provider office note
  Expected reimbursement: $0.00
  Allowed maximum: $1,450.00
  Amount paid: $0.00
- CL-2102 — auto claim from Feb 28, 2026 (open)
  Status: open — Auto claim in progress
  Expected reimbursement: $3,200.00
  Allowed maximum: $3,500.00
  Amount paid: $0.00

Next steps:
- CL-2048 — healthcare claim from Jan 12, 2026 (denied)
  Submit the pathology report and the office note
  Appeal deadline: 2026-03-18

How to reach us:
- Reply to this email or call the number on your insurance card to reach claims support.

Should I send this summary to your email now?

**Turn 5 — CLOSED / NONE**

I've sent the summary of our conversation to your email at m*****@email.com. Thank you for reaching out today, and take care!

### yawen_alias

**Turn 1 — RESOLVE_INTENT / NONE**

Thank you for verifying your identity. I have checked your account, and there are no claims on your policy at this time. Is there anything else I can help you with today?

