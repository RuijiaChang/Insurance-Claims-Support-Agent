# Demo script

Choose each preset in the scenario picker. It starts a fresh session and fills in the opener. Press **Send** to submit it. Suggestion chips send that line as your next message. Quick replies submit actions directly. Wording varies by model. The expected results describe the phase, access gate, and fixture facts to look for.

## 1. Margaret · denied claim

1. Send “I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.” Expect verification and selection of CL-2048 within the same turn. The Inspector shows the January denial hint captured in `VERIFY_ID` and used in `RESOLVE_INTENT`.
2. Ask “What exactly do I need to send?” Expect the original pathology report and treating provider office note, with the submission instructions grounded in the fixtures.
3. Ask “How soon do I need to submit?” Expect the fixture’s submission-timing guidance to send the documents within a week. Ask “How long after I submit?” to see the distinct processing guidance. The email preview includes the March 18, 2026 appeal deadline.
4. Say “That's all, thanks.” Expect an email offer. Choose **Yes, show me the summary** to preview the discussion, claim outcome, and next steps. Confirm **Send email** and open the Outbox to see the mock message. To exercise the skip branch, restart and choose **No thanks** at the offer.

## 2. Margaret · frustrated caller

1. Send “Hi, I'm Margaret Chen”. Expect a request for two more fields.
2. Send “I already told you who I am. This is ridiculous. Just tell me why my claim was denied.” Expect acknowledgment of the frustration, an explanation of why details are protected, and alternatives such as date of birth, phone, email, or ID suffix. The state remains `VERIFY_ID` with access off.
3. Send “My DOB is 1985-03-15 and my SSN last four is 4472. It's my denied healthcare claim from January.” Expect verification and claim selection.

## 3. David · consent approved

1. Send “Hi, I'm David Chen, calling for my mom Margaret Chen. Her DOB is 1985-03-15, SSN last four 4472, policy POL-9921.” Expect a matching representative and `CONSENT_PENDING` with access off.
2. Wait for the automatic consent polls. On approval, access turns on and the phase becomes `RESOLVE_INTENT`.
3. Ask “I'm calling about her denied healthcare claim from January.” Expect CL-2048. An email follow-up, if confirmed, goes to Margaret's registered address.

## 4. David · consent timeout

1. Use the same David opener as scenario 3. The preset selects the `timeout` consent sequence.
2. Wait until `CONSENT_EXPIRED`. Access remains off and the controls offer a resend, handoff, or an end to the session.
3. Choose **Talk to a representative**. Expect `HANDOFF` with a mock ticket and no claim disclosure.

## 5. Ya Wen · name alias

1. Send “This is Yaven Li, email yawen.li@example.com, phone 650-521-2830.” Expect the alias and two contact fields to verify the caller.
2. Ask “Can you tell me the status of my claims?” Expect a truthful statement that Ya Wen has no claims in the fixtures.

## 6. Ma Tian · national ID

1. Send “Ma Tian here, born 1964-09-10, national ID last four 6688.” Expect three matching fields and access.
2. Ask “Can you tell me the status of my claims?” Select CL-3001 if prompted. Expect a denied healthcare claim with a missing diagnosis report.

## 7. Ava · no claims

1. Send “Ava Lopez, DOB 1990-08-21, SSN last 4 is 9180, phone 650-388-2920.” Expect verification and a truthful empty-claim result.
2. Ask “Do I have any claims on file?” Expect confirmation that the fixture has no claims for Ava, with an offer of further help.

## 8. Repeated off-topic requests

1. Send “What is reinforcement learning?”
2. Send “Who won the World Cup?”
3. Send “Can you write me a poem?” Expect a polite redirect each time, with a human representative offered after the third request. Access stays off.

## 9. Margaret · verification lockout

1. Send “I'm Margaret Chen, DOB 1990-01-01, SSN last four 1111.”
2. Send “My DOB is 1990-01-02 and my SSN last four is 2222.”
3. Send “My DOB is 1990-01-03 and my SSN last four is 3333.” Expect generic feedback on unsuccessful comparisons, followed by lockout and `HANDOFF` on the third attempt. The mock ticket carries no claim data.
