# Demo walkthrough (about 10 minutes)

Start the stack with `start.bat` and sign in as `owner@brightwork.test` (password `resolveflow-demo`). Mailpit is open at http://localhost:8025.

## 1. A customer writes in
1. Open http://localhost:3000/form/brightwork in a private window and send a message with the subject "Refund for my order".
2. Back in the app, the new ticket is already **High** priority, tagged **refund**, and assigned to a teammate. Open it and expand **Automations that ran** to see the rule that did it and what each action did.

## 2. The clock is real
1. Open any ticket and the **Service levels** panel: the deadlines are counted in business hours. Choose **How is this calculated?** to see every pause and resume.
2. Set the status to **Pending**: the first-response clock pauses. Set it back to **Open** and it resumes.
3. Open **Service levels** in the sidebar, shorten the Urgent target, save, and watch an urgent ticket's deadline move.

## 3. Build an automation you can trust
1. Open **Automations** and choose **New automation**. Trigger: a new ticket. Condition: subject contains "invoice". Action: assign to the Support team (round-robin).
2. Save, then use **Test it** with a made-up ticket. Nothing real changes. Record it as a test.
3. **Make live** is now enabled. Edit the rule and it locks again until the new version has its own passing test. Older tested versions can be rolled back to.

## 4. Email and notifications
1. In **Channels**, send a simulated email. It becomes a ticket, and replies thread onto it.
2. Reply to a ticket. The reply shows up in Mailpit.
3. Sign in as `agent@brightwork.test` in another window. When the owner assigns that agent a ticket, the bell shows it within seconds. Open **Notifications** to change what reaches you.

## 5. Find things and see how the team is doing
1. **Search** for a word that appears inside a message, not just the subject. Matches are highlighted.
2. Click a requester on a ticket to see that customer's full history.
3. Open **Analytics**: SLA compliance, response times and volume by day, priority, channel and teammate.

## 6. Privacy
Open **Privacy**, choose a retention period and see how many tickets are past the limit. Erasing needs an explicit confirmation.

## Reset
`reset.bat` deletes everything and the next start re-creates the demo workspace.
