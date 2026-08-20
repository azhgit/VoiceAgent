# Voice Agent POC

A Twilio-connected voice agent that takes after-hours plumbing/HVAC calls,
judges urgency, and books or escalates against a mock CRM. Built as a
job-application demo for a voice-agent engineering role.

## Language

**Urgent case**:
A caller report matching a fixed symptom category: active water damage, no
heat with freezing temperatures, a gas smell, or sewage backup. Triggers the
Handoff simulation instead of the booking flow.
_Avoid_: Emergency — vague; "urgent case" names the fixed-category rule
that decides it.

**Non-urgent case**:
Any caller report that doesn't match the Urgent case category list (e.g.
dripping faucet, no hot water, general noise/maintenance). Goes through the
booking flow.

**Technician**:
An entity in the mock CRM representing a dispatchable worker: name,
specialty, on-call flag. Assigned to Appointments.
_Avoid_: Worker, staff, agent — "agent" is reserved for the voice agent
itself.

**Appointment**:
A booking record in the mock CRM: technician_id, time slot, customer info,
urgency flag, status.
_Avoid_: Booking, reservation, ticket

**Handoff simulation**:
The scripted response to an Urgent case with no on-call Technician
available, or a caller who remains unintelligible after one retry: the
agent announces a transfer ("connecting you to our on-call technician now")
and ends the call. No actual telephony transfer occurs.
_Avoid_: Escalation, transfer — those imply a real handoff mechanism, which
this deliberately isn't.

**Callback promise**:
The agent's response to a Non-urgent case with no matching Appointment slot
in the seeded schedule window: offers the nearest available time outside
that window, and tells the caller someone will call back sooner if a
cancellation opens up.
