---
title: Submission, revision, and withdrawal policy 0.1
summary: This page explains how candidate records are reviewed, published, revised, withdrawn, and attributed.
---

This is the user-facing governance policy for the Circuit Bench 0.1 development prototype.

## New submissions

- Decoder versions, circuit revisions, and results enter `pending_review`, even when an administrator submits them.
- Machines publish immediately after validation. Their automatic approval is attributed to **System**, not to the uploader.
- Results can be submitted only when their decoder version, circuit revision, evaluator release, and machine are already published.

## Editing and revisions

- A `pending_review` or `pending_reapproval` candidate can be edited in place. Its exact candidate UUID is retained and the edit is recorded in its moderation history.
- A published record is immutable. “Edit / new revision” creates a separate successor candidate. For decoder and circuit revisions, the uploader explicitly chooses either to leave the predecessor published alongside the candidate or to withdraw it while submitting the successor for reapproval. Neither choice changes the predecessor’s scientific content.
- A withdrawn record is also immutable. “Revise and resubmit” creates a separate successor in `pending_reapproval`.
- A successor to a withdrawn machine requires human reapproval even though an ordinary new machine publishes automatically.

## Withdrawal

The uploader or an administrator can withdraw a published record after confirming the action and giving a reason. Withdrawal does not delete or rewrite the exact record: its permanent page, timestamps, lineage, and moderation history remain available, marked as withdrawn.

## Approval attribution

Every publication made through this workflow records who approved it. Manual review records the administrator’s account. Policy-driven publication records **System**. Older development fixtures for which no approval event exists are labelled “Not recorded (legacy)” rather than receiving a guessed attribution.

## Administration

The admin page is a work queue, not a catalogue. It contains records waiting for review and a separate audit table of records withdrawn during the preceding seven days.

## Audit and policy changes

Submission, editing, resubmission, approval, publication, and withdrawal write permanent moderation events. The selected approval route and policy version are recorded with the event. Future policy versions may relax review for specific kinds or trusted uploaders without changing the scientific record definitions.
