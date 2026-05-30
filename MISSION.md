# Mission

Prepare this repo to become a complete end-to-end marketing automation platform for our own agency workflow.

The real goal is to scale our own marketing to around 10x the current ad spend, receive around 10x more people in the funnel, and convert them without needing us to manually handle every lead, every reply, every client update, every ad creation step, and every delivery step.

This should not become just a chatbot or just a CRM. It should become a full internal platform where our marketing, lead handling, WhatsApp conversations, meetings, ad creation, Meta Ads publishing, Google Sheets lead delivery, client reporting, and operator oversight are streamlined.

## Main workflow

The platform should support this full cycle:

1. We run ads.
2. Leads arrive in Google Sheets.
3. The platform reads and handles those leads.
4. The platform sends WhatsApp messages using a sequence like the one we already have now.
5. At some point, AI should take over parts of the conversation when the fixed sequence is not enough.
6. The AI should know how to answer doubts, qualify leads, and push toward the next step.
7. The main conversion flow is to send a Loom-style video and then get the person into a meeting with us to clear final doubts.
8. Calendly does not seem to work well enough, so the bot should be able to ask for date and time, understand the lead’s timezone, ask for email, and create a Google Calendar event.
9. Calendar events should include the lead, yoelkravchuk@gmail.com, and facundogoiriz@gmail.com.
10. The event should include useful context from the conversation.
11. The real conversion and payment collection usually happen during the meeting with us.
12. After conversion, I will provide the transcript of the meeting.
13. From that transcript, the platform should understand the client, their business, their offer, their objections, their market, and their needed segmentation.
14. Then the platform should create ad ideas, create the ad images using Codex image generation if available, save the ads, publish them to Meta Ads, use the same or similar budgets as we currently use, and start delivery.
15. The leads from the campaign should go into Google Sheets and be added to delivery so the client receives the leads.
16. The platform should send WhatsApp updates to clients every 24 hours, such as:
    - “Hey, it’s running.”
    - “X new leads arrived.”
    - “No leads arrived yet, but I think it may be because it’s the weekend.”
    - other useful status updates.
17. The platform should also solve client doubts, not just send status messages.

## Repo understanding requirement

Before designing or coding, inspect everything available:

- the full repo
- current backend
- current frontend
- current skills
- current CRM logic
- current message sequences
- current Google Sheets handling
- current WhatsApp handling
- current client conversations
- current CRM conversations
- current manual workflows
- current ad workflow
- current budgets
- current offer
- current delivery process
- current frontend clutter
- current backend clutter

The point is to understand exactly what we currently do manually and turn that into a platform.

## Research requirement

For each major part, research best practices first. Do not guess.

Research:

- how strong marketing automation products are built
- how good marketing CRMs are built
- how agents for marketing are built
- how WhatsApp chatbots are built
- how human handoff and escalation should work
- how to build AI agents with memory and context
- how to structure DSPy projects well
- how good DSPy repos look
- how DSPy should be used for this kind of system
- whether DSPy should be used instead of, or together with, Codex SDK
- how Codex SDK should be used
- how OpenClaw works and whether it is useful here
- how Hermes works and whether it is useful here
- whether RabbitMQ, Kafka, or another queue/background system is needed
- how to build full observability for agent systems
- how to stream agent work, checkpoints, errors, and progress
- how to safely run parallel agents that may ask for human help
- how to save new human answers into reusable skills or knowledge
- how to design the platform so a new employee can operate it

## AI architecture preference

Use DSPy where it makes sense for:

- marketing reasoning
- message generation
- Q&A behavior
- lead conversation logic
- reusable programs
- evaluation
- prompt/program structure
- personality and response consistency

Use Codex SDK where it makes sense for:

- agent execution
- repo-level automation
- tool use
- image generation if available
- creating ads
- saving artifacts
- publishing workflows
- per-user or per-client threads
- keeping execution context
- long-running workflows

Do not assume either DSPy or Codex SDK should do everything. Research and decide the cleanest architecture.

Each client or user may have their own thread/context if that makes the system easier to manage.

## Bot behavior and company context

The bot should not only answer from a list of FAQs.

It should understand the full company context, objectives, incentives, offer, client type, sales process, previous manual replies, common objections, and tone.

The goal is for the bot to replace what we manually do, as closely as possible.

It should:

- sound human
- sound like us
- respond like we would respond
- understand why we respond a certain way
- know what to say when a lead asks a known question
- infer what to say when a lead asks a new question
- use full context, not just canned answers
- build a strong personality/context layer
- include frequent Q&A, but not depend only on FAQ matching
- learn from past client conversations
- learn from CRM conversations
- learn from WhatsApp conversations
- save reusable knowledge into skills or an internal knowledge base

The desired feeling is: the bot knows the company like I know the company, so it can answer new questions using the same context I would use.

## Offer update

Old Loom videos are not updated because we used to offer something around $299.

The new offer we want to test is:

- $599
- single monthly payment
- we handle ads
- we handle the marketing work
- the client pays and gets clients/leads to their WhatsApp
- if the client does not have a website, we can create one included

Website creation itself does not need to be automated now. Facundo will handle website creation separately.

What matters here is the automation after we say: “I converted this user. Here is the meeting transcript.”

From there, the platform should know what ads to create, what segmentation to use, how to publish, how to deliver leads, and how to update the client.

## Conversion flow

Current conversion logic:

- lead enters funnel
- we send messages
- we send a Loom-style video
- we invite them to a meeting
- meeting clears final doubts
- we collect payment in the meeting
- during the meeting, we collect key info needed for ads and segmentation
- after conversion, the meeting transcript is the handoff point
- the platform takes the transcript and continues the client onboarding/ads workflow

This means the system has two big phases:

1. Pre-conversion: lead handling, WhatsApp conversation, video, meeting booking.
2. Post-conversion: use meeting transcript to create and run ads, deliver leads, update client, and answer client questions.

## Human doubt escalation

The platform should be very autonomous, but when an agent has a real doubt, it should have a quick way to ask Facundo through WhatsApp.

The message to Facundo should include:

- the agent/workflow that is asking
- the client or lead context
- what the agent is trying to do
- the exact doubt
- the options the agent is considering if any
- what will happen if Facundo does not answer

Try sending a normal WhatsApp message first.

If the 24-hour WhatsApp window is closed, send a WhatsApp template message instead. The needed template should be created as part of the system.

There may be many parallel agents asking doubts. Facundo may answer by replying to a specific WhatsApp message. The platform should know which question he replied to and wake up the right agent or workflow.

The agent should not necessarily wait forever. It can ask, wait a short time such as around 4 minutes, and if there is no answer, continue with its own assumption when safe. If Facundo answers later, the answer should still be saved as useful knowledge or a skill so the same doubt is avoided next time.

This should feel autonomous, but still allow fast human help.

## Ads concept and copy direction

I like this ad/copy concept:

The fastest way to kill objections before they are even spoken:

Step 1: Take what they want.
Step 2: Add the word “without”.
Step 3: Add the thing they hate most.

Examples:

- “Keep your hair without choking down a pill every morning.”
- “Reduce stubborn fat without giving up the food you actually like.”
- “Calm your dog’s itching without another $200 vet visit.”

That one word does more objection handling than three paragraphs of copy.

“Skip the pills, keep the hair” is not just a benefit. It removes the buyer’s biggest excuse before they say it.

For our own ads, possible angles:

- “Get new clients without recording Instagram videos.”
- “Get new clients without posting every day.”
- “Get new clients without paying thousands to an agency.”
- “Grow your business without becoming a content creator.”
- “More clients to your WhatsApp without learning ads yourself.”
- “Run ads without hiring an expensive agency.”
- “Get clients online without making reels every week.”

Research and improve these ideas based on current best practices for direct response ads, Meta Ads, WhatsApp funnels, objections, and our current offer.

## Frontend/platform requirement

The frontend should become much better.

It should feel like a complete internal platform for us, not a random tool.

It should be intuitive enough that a new employee can understand how to operate it.

It should show:

- funnels
- leads
- lead status
- WhatsApp conversation state
- AI status
- current sequence step
- scheduled follow-ups
- booked meetings
- converted clients
- post-conversion onboarding
- ad creation progress
- Meta Ads publishing status
- campaign budgets
- Google Sheets delivery status
- client updates sent
- agent questions/doubts
- errors
- logs
- checkpoints
- model activity
- what Codex or agents are doing
- streaming progress where useful
- current blockers
- retry options
- manual override options

Full observability is very important.

We need to understand what is happening at every step.

## Backend/platform requirement

The backend should support:

- Google Sheets ingestion
- lead state tracking
- WhatsApp messaging
- message sequences
- AI handoff
- AI-generated replies
- CRM context
- client context
- meeting scheduling
- Google Calendar event creation
- meeting transcript ingestion
- post-conversion client onboarding
- ad strategy generation
- image generation
- Meta Ads publishing
- lead delivery
- client status updates
- human escalation
- agent workflow state
- queues/background jobs if needed
- error tracking
- retries
- observability
- streaming/checkpoint events
- skills or knowledge updates

You are allowed to redesign backend and frontend.

You are allowed to delete clutter if it hurts the platform.

You are allowed to add new tech if research shows it is needed.

Do not over-engineer without justification.

## Codex / auth requirement

I want to do Codex login through ChatGPT subscription if possible.

API key mode is also fine.

If ChatGPT subscription login requires me and I am not available, continue with API key mode.

Do not waste a lot of time blocked on login choice.

## Delivery style

Work in phases.

First inspect and research.

Then propose architecture.

Then update the repo safely.

Then create a clear implementation roadmap.

Then implement the highest-value base platform pieces.

Always keep the system aligned with the real business goal: scaling our marketing and operations without needing us to manually handle every lead, client, ad, update, and doubt.

If something is unclear, make a reasonable assumption, continue if safe, and write down the assumption. If the assumption is risky, escalate to Facundo using the WhatsApp doubt mechanism.