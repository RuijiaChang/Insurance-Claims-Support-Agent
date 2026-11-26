# Live-model evaluation report

Run: 2026-11-26T21:27:36.341839+00:00
Provider: openai; model: gpt-4.1-mini; demo date: 2026-03-05.

Real model calls; consent polls use the same deterministic bundle as the API. LLM errors fail a scenario even if fallback reaches the expected state. Guard violations (including email polish), leaks and unsafe template fallbacks fail.

| Scenario | Result | Final phase | Leaks | Guard violations | LLM errors | p50 (s) | p95 (s) |
|---|---|---|---:|---:|---:|---:|---:|
| angry | PASS | VERIFY_ID | 0 | 0 | 0 | 2.42 | 2.64 |
| ava_no_claims | PASS | RESOLVE_INTENT | 0 | 0 | 0 | 2.06 | 2.06 |
| david_default | PASS | PROCESS_CASE | 0 | 0 | 0 | 2.30 | 2.78 |
| david_timeout | PASS | HANDOFF | 0 | 0 | 0 | 2.16 | 2.16 |
| margaret | PASS | CLOSED | 0 | 0 | 0 | 2.23 | 2.90 |
| off_topic | PASS | HANDOFF | 0 | 0 | 0 | 2.30 | 2.68 |
| switch_case | PASS | CLOSED | 0 | 0 | 0 | 2.28 | 2.82 |
| yawen_alias | PASS | RESOLVE_INTENT | 0 | 0 | 0 | 2.02 | 2.02 |

## Conversation evidence

### angry

**Turn 1 — VERIFY_ID / COLLECTING**

Thank you, Margaret. To verify your identity, please provide two more details from your date of birth, phone number, email address, or the last four digits of your SSN or national ID.

**Turn 2 — VERIFY_ID / COLLECTING**

I understand how frustrating it is to repeat your information when you want answers quickly. Verifying your identity protects your private claim details from being shared with anyone else. I noted you mentioned your claim was denied, and I can review that once we complete verification. Please provide two more details from your date of birth, phone number, email, or last four digits of your SSN.

### ava_no_claims

**Turn 1 — RESOLVE_INTENT / NONE**

Thank you, you are now verified. I see there are no claims on your policy at this time. Is there anything else I can assist you with today?

### david_default

**Turn 1 — VERIFY_ID / CONSENT_PENDING**

A consent request has been sent to the policyholder's phone on file ending in 36. Once she approves it, I can continue helping you with the claims. Let me know if you have any questions in the meantime.

**Turn 2 — VERIFY_ID / CONSENT_PENDING**

I'm still waiting for the policyholder to approve the consent request.

**Turn 3 — RESOLVE_INTENT / NONE**

The policyholder has approved — I can now help you with their claims.

**Turn 4 — PROCESS_CASE / ACTIVE**

I see the healthcare claim from January 12, 2026, was denied because the pathology report and the treating provider's office note were missing. You can submit these documents through the member portal or claim upload link, ensuring they are complete and legible. Once we receive and review these files, the claim will be re-evaluated, which might take another review cycle. Is there anything else you'd like to know about this claim?

### david_timeout

**Turn 1 — VERIFY_ID / CONSENT_PENDING**

A consent request was sent to the policyholder's phone on file at ***-***-**36. Once she approves it, I can continue helping you with the claims. Let me know if there's anything else you'd like to ask meanwhile.

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

I've passed your conversation to a representative who will follow up with you under ticket HT-f269cd. Thank you for reaching out today.

### margaret

**Turn 1 — PROCESS_CASE / ACTIVE**

I see you are asking about your denied healthcare claim from January. You are verified. The healthcare claim from January 12, 2026, is denied due to missing the pathology report and the treating provider office note. The appeal deadline is March 18, 2026, so you still have time to submit these documents for reconsideration. Is there anything else you would like to know about this claim?

**Turn 2 — PROCESS_CASE / ACTIVE**

You need to send the pathology report and the office note. The pathology report should include the patient name, specimen details, testing date, and the clinician or lab signature if available. The office note should show the patient name, visit date, assessment, and treatment or follow-up recommendation, ideally uploaded as one PDF. Once these readable files are received, the claim will go back into review and may need another review cycle before the status changes. Is there anything else I can help with on this claim?

**Turn 3 — PROCESS_CASE / ACTIVE**

For claim CL-2048, please submit the pathology report and the office note within a week. Is there anything else you would like to know about this claim?

**Turn 4 — POST_PROCESS / OFFER**

I can email you a summary of our conversation at m*****@email.com if you'd like. Would you like me to send it?

**Turn 5 — POST_PROCESS / PREVIEW**

Here's a summary of our conversation for your reference:

Subject: Summary of your claims support conversation

What we discussed:
- We talked about your healthcare claim from January 12, 2026, which was denied because the pathology report and the treating provider's office note were missing.

Claim status / outcome:
- CL-2048: Status: denied — Healthcare claim denied due to missing pathology report and office note
- CL-2048: Denial reason: the review file did not include the pathology report and the treating provider office note

Next steps:
- CL-2048: Submit the pathology report and the office note
- CL-2048: Appeal deadline: 2026-03-18
- CL-2048: For claim CL-2048, please submit the pathology report and the office note within a week.

How to reach us:
- Reply to this email or call the number on your insurance card to reach claims support.

Would you like me to send this summary to your email now?

**Turn 6 — CLOSED / NONE**

I've sent the summary to your email at m*****@email.com. Thank you for contacting us, and take care!

### off_topic

**Turn 1 — VERIFY_ID / COLLECTING**

I can only assist with insurance claims and policy questions. To help you with your claim, please provide any three of these details: your full name, date of birth, phone number, email address, or the last four digits of your SSN or national ID.

**Turn 2 — VERIFY_ID / COLLECTING**

I’m here to assist with insurance claims and policy questions only. To proceed with your claim inquiry, please provide any three of these identity details: your full name, date of birth, phone number, email address, or the last four digits of your SSN or national ID.

**Turn 3 — VERIFY_ID / COLLECTING**

I can only help with insurance claims and policy questions. If you'd like, I can connect you with a representative who might assist further. Meanwhile, to help with your claim, please provide any three of these: your full name, date of birth, phone number, email address, or the last four digits of your SSN or national ID.

**Turn 4 — HANDOFF / NONE**

I will connect you with a representative who can assist you further. They will follow up on your inquiry.

### switch_case

**Turn 1 — PROCESS_CASE / ACTIVE**

I see you mentioned your denied healthcare claim from January. You are verified now. I've pulled up your healthcare claim from January 12, 2026, which was denied. The claim was denied because the review file did not include the pathology report and the treating provider office note; once you submit these missing documents, the claim will be reviewed again and may need another review cycle before the status changes. Is there anything else you would like to know about this claim?

**Turn 2 — PROCESS_CASE / ACTIVE**

I've selected your open auto claim from February 28, 2026. This claim is still in progress with an expected reimbursement amount of $3,200, and no payment has been made yet. I don't have more detailed status updates beyond that right now. Is there anything else you'd like to know about this auto claim?

**Turn 3 — POST_PROCESS / OFFER**

Would you like me to email a summary of our conversation to your address on file, m*****@email.com? You can say yes to receive it or skip if you prefer.

**Turn 4 — POST_PROCESS / PREVIEW**

Here's a summary draft of our conversation for your review:

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

I've sent a summary of our conversation to your email at m*****@email.com. Thank you for reaching out today, and take care!

### yawen_alias

**Turn 1 — RESOLVE_INTENT / NONE**

Thank you for verifying your identity. I have checked your account, and there are currently no claims on your policy. Is there anything else I can assist you with today?

