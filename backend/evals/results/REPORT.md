# Live-model evaluation report

Run: 2026-11-26T21:31:51.088472+00:00
Provider: openai; model: gpt-4.1-mini; demo date: 2026-03-05.

Real model calls; consent polls use the same deterministic bundle as the API. LLM errors fail a scenario even if fallback reaches the expected state. Guard violations (including email polish), leaks and unsafe template fallbacks fail.

| Scenario | Result | Final phase | Leaks | Guard violations | LLM errors | p50 (s) | p95 (s) |
|---|---|---|---:|---:|---:|---:|---:|
| angry | PASS | VERIFY_ID | 0 | 0 | 0 | 2.51 | 2.63 |
| ava_no_claims | PASS | RESOLVE_INTENT | 0 | 0 | 0 | 2.15 | 2.15 |
| david_default | PASS | PROCESS_CASE | 0 | 0 | 0 | 2.24 | 2.67 |
| david_timeout | PASS | HANDOFF | 0 | 0 | 0 | 2.23 | 2.23 |
| margaret | PASS | CLOSED | 0 | 0 | 0 | 2.20 | 2.64 |
| off_topic | PASS | HANDOFF | 0 | 0 | 0 | 2.17 | 2.67 |
| switch_case | PASS | CLOSED | 0 | 0 | 0 | 2.30 | 2.30 |
| yawen_alias | PASS | RESOLVE_INTENT | 0 | 0 | 0 | 2.30 | 2.30 |

## Conversation evidence

### angry

**Turn 1 — VERIFY_ID / COLLECTING**

Thank you, Margaret. To verify your identity, could you please provide two more details from your date of birth, phone number, email address, or the last four digits of your SSN?

**Turn 2 — VERIFY_ID / COLLECTING**

I understand how frustrating it is to repeat your information when you're eager to know why your claim was denied. This verification step keeps your personal and claim details safe from unauthorized access. You mentioned wanting to know why your claim was denied, and I’ll be able to help with that once we confirm your identity. Please provide two more details like your date of birth, phone number, email, or the last four digits of your SSN.

### ava_no_claims

**Turn 1 — RESOLVE_INTENT / NONE**

Thank you, you are now verified. I checked your policy and there are no claims on it at this time. Is there anything else I can help you with today?

### david_default

**Turn 1 — VERIFY_ID / CONSENT_PENDING**

A consent request has been sent to the policyholder's phone on file at ***-***-**36. Once your mom approves it, I can continue helping you with her claims.

**Turn 2 — VERIFY_ID / CONSENT_PENDING**

I'm still waiting for the policyholder to approve the consent request.

**Turn 3 — RESOLVE_INTENT / NONE**

The policyholder has approved — I can now help you with their claims.

**Turn 4 — PROCESS_CASE / ACTIVE**

The healthcare claim from January 12, 2026, was denied because the review file did not include the pathology report and the treating provider office note. To move forward, you can submit these missing documents through the member portal or claim upload link, making sure they are complete and legible. Is there anything else you'd like to know about this claim?

### david_timeout

**Turn 1 — VERIFY_ID / CONSENT_PENDING**

A consent request has been sent to the policyholder's phone on file at ***-***-**36. Once she approves it, I can continue helping you with the claims.

**Turn 2 — VERIFY_ID / CONSENT_PENDING**

I'm still waiting for the policyholder to approve the consent request.

**Turn 3 — VERIFY_ID / CONSENT_PENDING**

I'm still waiting for the policyholder to approve the consent request.

**Turn 4 — VERIFY_ID / CONSENT_PENDING**

I'm still waiting for the policyholder to approve the consent request.

**Turn 5 — VERIFY_ID / CONSENT_PENDING**

I'm still waiting for the policyholder to approve the consent request.

**Turn 6 — VERIFY_ID / CONSENT_EXPIRED**

The consent request expired before the policyholder approved it. I can resend it once, connect you with a representative, or we can end here.

**Turn 7 — HANDOFF / NONE**

I've passed your conversation to a representative who will follow up with you under ticket HT-699b10. They will assist you further.

### margaret

**Turn 1 — PROCESS_CASE / ACTIVE**

Thank you for verifying your identity. You have a healthcare claim from January 12, 2026, which was denied because the pathology report and the treating provider's office note were missing. To move forward, you can submit these documents through the member portal or claim upload link, ensuring they are complete and legible. Is there anything else you'd like to know about this claim?

**Turn 2 — PROCESS_CASE / ACTIVE**

You need to send the pathology report, which should include patient name, specimen details, testing date, and clinician or lab signature if available, and the office note showing patient name, visit date, assessment, and treatment or follow-up recommendation. For submitting these, the best starting point is usually the member portal or claim upload link so the documents stay attached to the file. If online upload isn't available, support can help arrange fax or mail submission. Is there anything else I can help with on this claim?

**Turn 3 — PROCESS_CASE / ACTIVE**

For claim CL-2048, please submit the pathology report and the office note within a week. Is there anything else I can help with on this claim?

**Turn 4 — POST_PROCESS / OFFER**

I can email you a summary of our conversation to m*****@email.com if you'd like. Would you like me to send it?

**Turn 5 — POST_PROCESS / PREVIEW**

Here's a draft of the summary email I can send you:

Subject: Summary of your claims support conversation

What we discussed:
- We talked about your healthcare claim from January 12, 2026, which was denied because the pathology report and the treating provider's office note were missing.

Claim status / outcome:
- CL-2048: Status: denied — Healthcare claim denied due to missing pathology report and office note
- CL-2048: Denial reason: the review file did not include the pathology report and the treating provider office note

Next steps:
- CL-2048: Submit the pathology report and the office note
- CL-2048: Appeal deadline: 2026-03-18
- CL-2048: For claim CL-2048, the best starting point is usually the member portal or the claim upload link so the pathology report and the office note stay attached to the file. If online upload is not available, support can help arrange fax or mail handling.
- CL-2048: For claim CL-2048, please submit the pathology report and the office note within a week.

How to reach us:
- Reply to this email or call the number on your insurance card to reach claims support.

Shall I send this summary to your email?

**Turn 6 — CLOSED / NONE**

I've sent the summary of our conversation to your email at m*****@email.com. Thank you for reaching out, and take care!

### off_topic

**Turn 1 — VERIFY_ID / COLLECTING**

I can only assist with insurance claims and policy questions. To continue, please provide any three of these identity details: full name, date of birth, phone number, email address, or the last four digits of your SSN or national ID.

**Turn 2 — VERIFY_ID / COLLECTING**

I’m here to help with insurance claims and policy questions only. To proceed, please provide any three of these identity details: full name, date of birth, phone number, email address, or the last four digits of your SSN or national ID.

**Turn 3 — VERIFY_ID / COLLECTING**

I can only help with insurance claims and policy questions. If you'd like, I can connect you with a representative who might assist further. Meanwhile, please provide any three of these identity details: full name, date of birth, phone number, email address, or the last four digits of your SSN or national ID.

**Turn 4 — HANDOFF / NONE**

I have passed your conversation to a representative who will follow up with you. Have a good day!

### switch_case

**Turn 1 — PROCESS_CASE / ACTIVE**

Thank you for verifying your identity. I've pulled up your healthcare claim from January 12, 2026, which was denied. The denial was because the pathology report and the treating provider's office note were missing from the review file. Is there anything else you'd like to know about this claim?

**Turn 2 — PROCESS_CASE / ACTIVE**

I've found your open auto claim from February 28, 2026. I don't have additional details beyond its status and expected reimbursement amount of $3,200. Is there anything else you want to know about this auto claim?

**Turn 3 — POST_PROCESS / OFFER**

I can email you a summary of our conversation to m*****@email.com if you'd like. Would you like me to send it?

**Turn 4 — POST_PROCESS / PREVIEW**

Here is a summary draft of our conversation for your review:

Subject: Summary of your claims support conversation

What we discussed:
- We talked about your healthcare claim from January 12, 2026, which was denied because the pathology report and office note were missing, and your auto claim from February 28, 2026, which is still open.

Claim status / outcome:
- CL-2048: Status: denied — Healthcare claim denied due to missing pathology report and office note
- CL-2048: Denial reason: the review file did not include the pathology report and the treating provider office note
- CL-2102: Status: open — Auto claim in progress

Next steps:
- CL-2048: Submit the pathology report and the office note
- CL-2048: Appeal deadline: 2026-03-18

How to reach us:
- Reply to this email or call the number on your insurance card to reach claims support.

Shall I send this summary to your email now?

**Turn 5 — CLOSED / NONE**

I've sent the summary of our conversation to your email at m*****@email.com. Thank you for reaching out today, and take care!

### yawen_alias

**Turn 1 — RESOLVE_INTENT / NONE**

Thank you, you are now verified. I checked your account, and there are no claims on your policy at this time. Is there anything else I can help you with?

