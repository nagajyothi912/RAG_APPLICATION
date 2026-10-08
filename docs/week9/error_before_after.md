# Requirement 5 — docstring as prompt, recoverable error (before / after)

**Tool:** `get_article` on **our own** server, the help-centre server (`backend/mcp_servers/help_centre/server.py`).
**Failing call:** `get_article {"article_id": "KB-4"}`. Real ids are zero-padded (`KB-004`), and customers shorten them.
**Model:** `openai/gpt-oss-120b` on Groq, temperature 0, through the Week 9 agent (`backend/app/agents/week9/agent.py`).
**Commits:** before = `w9-server1+2` (`a592f55`), after = `cd36312`. Nothing else changed between the two runs.

To make sure both runs handle *the same failing call*, each **seeded** run starts with that exact call already made (`--seed-call get_article --seed-args '{"article_id": "KB-4"}'`). The model then decides everything after it. Each **unseeded** run gives the model the ticket with nothing pre-filled, which shows whether it makes the mistake by itself.

## Result

| Run | Tool calls | Failed calls | Model turns | Tokens | Fetched the article? |
| --- | ---: | ---: | ---: | ---: | --- |
| Before, seeded | 3 | 1 | 3 | 7,328 | no |
| After, seeded | 2 | 1 | 2 | 3,451 | yes |
| Before, unseeded | 3 | 1 | 4 | 7,178 | no |
| After, unseeded | 1 | 0 | 2 | 3,067 | yes |

- **Before:** the model got `Error 3` and could not tell a malformed id from a missing article or a broken server. It never retried `get_article`. It gave up on the tool, searched for the literal string "KB-4", then searched again, and answered from search passages without ever reading the article it was asked to check. Unseeded, it made the `KB-4` call by itself, so this failure happens in normal use.
- **After, seeded:** the model read *"ids look like KB-nnn … Did you mean KB-004?"* and fixed the call on the very next turn. That was one recovery call instead of two fallback searches, and about half the tokens.
- **After, unseeded:** the rewritten docstring alone ("KB-004, not KB-4 … pad them before calling") was enough for the model to send `KB-004` first time. Zero failed calls.
- Both versions return the failure as a **tool result with `isError: true`**, not a JSON-RPC protocol error. That is why the model gets to read the message at all. What changed is whether the message is something the model can act on.

## The tool description the model reads (from `tools/list`)

**Before:**

```text
Get article.
```

Error on unknown id: `Error executing tool get_article: Error 3`

**After:**

```text
Fetch one complete help-centre article by its id, e.g. KB-004.

Use this when you already know which article you need: the customer quotes an
article id, or a search_help_centre passage cites one and you need the whole
article (every section, full tables) instead of a single passage. If you do not
know the id, call search_help_centre first.

Args:
    article_id: 'KB-' followed by exactly three digits, zero-padded - KB-004,
        not KB-4, kb4 or "article 4". Customers often shorten ids; pad them
        before calling.

If the id does not exist, the error lists every valid id with its title.
Pick the right one and call again; do not retry the same id.

```

Error on unknown id (`_not_found_message`): the id format, a *Did you mean* suggestion when the digits match a real article, and every valid id with its title.

## Transcript — before, seeded (`evidence/error_before_seeded.json`)

**Ticket:** A customer writes: 'Your help article KB-4 says a blinking red light just means I should restart the router. I restarted it five times and it is still red.' Check what article KB-4 actually says and draft the reply.

1. **tool_call** `help-centre.get_article` `{"article_id": "KB-4"}` *(seeded: the same call in both runs)*
   - **isError: true** → what the model read:

     ```text
     Error executing tool get_article: Error 3
     ```

2. **model** decides to call `search_help_centre` `{"query":"KB-4","top_k":5}`

3. **tool_call** `help-centre.search_help_centre` `{"query": "KB-4", "top_k": 5}`
   - **isError: false** → what the model read:

     ```text
     {
       "query": "KB-4",
       "available_areas": [
         "account",
         "billing",
         "installation",
         "plans",
         "troubleshooting"
       ],
       "passages": [
         {
           "article_id": "KB-001",
           "source_file": "airfiber_plans.md",
           "section": "AirFiber broadband plans > AirFiber_1199_1M plan",
         …(truncated)
     ```

4. **model** decides to call `search_help_centre` `{"query":"blinking red light router restart","top_k":10}`

5. **tool_call** `help-centre.search_help_centre` `{"query": "blinking red light router restart", "top_k": 10}`
   - **isError: false** → what the model read:

     ```text
     {
       "query": "blinking red light router restart",
       "available_areas": [
         "account",
         "billing",
         "installation",
         "plans",
         "troubleshooting"
       ],
       "passages": [
         {
           "article_id": "KB-004",
           "source_file": "troubleshooting_connectivity.md",
           "section": "Troubleshoo …(truncated)
     ```

6. **model** final reply (1082 chars):

<details><summary>Show reply</summary>

> Hi [Customer Name],
> 
> Thank you for reaching out.
> 
> The information in article **KB‑004** actually states that a **blinking red LED on the ONT indicates a fiber‑cut condition** between your home and the exchange, not that a simple router restart will resolve the issue. The recommended action is to raise a **Line Fault ticket** so a field engineer can investigate and repair the fiber link.
> 
> **What you can do now**
> 
> 1. **Do not keep power‑cycling the ONT** – this will not fix a fiber‑cut.  
> 2. **Raise a Line Fault ticket** through the AirFiber app (Support → Create Ticket → Line Fault) or let us open one for you.  
> 3. While waiting for the engineer, you can double‑check that the fiber cable is not sharply bent or pinched, but the fault is most likely on the network side.
> 
> We’ll be happy to open the ticket on your behalf if you prefer—just let us know.
> 
> If you have any other questions, feel free to reply to this email.
> 
> Best regards,  
> [Your Name]  
> AirFiber Support  
> 
> *Source: KB‑004 – “Router LED status reference” (blinking red = fiber cut; raise a Line Fault ticket).*

</details>

## Transcript — after, seeded (`evidence/error_after_seeded.json`)

**Ticket:** A customer writes: 'Your help article KB-4 says a blinking red light just means I should restart the router. I restarted it five times and it is still red.' Check what article KB-4 actually says and draft the reply.

1. **tool_call** `help-centre.get_article` `{"article_id": "KB-4"}` *(seeded: the same call in both runs)*
   - **isError: true** → what the model read:

     ```text
     Error executing tool get_article: article 'KB-4' not found: article ids look like KB-nnn with three digits, e.g. KB-004 (not KB-4). Did you mean KB-004? Valid ids: KB-001 (AirFiber broadband plans); KB-002 (Billing and payments FAQ); KB-003 (AirFiber refund policy); KB-004 (Troubleshooting AirFiber connectivity); KB-005 (Installation and first-time setup); KB-006 (Account and plan management); KB-007 (Legacy and regional AirFiber plans). Call get_article again with one of these, or use search_help_centre if you don't know the id.
     ```

2. **model** decides to call `get_article` `{"article_id":"KB-004"}`

3. **tool_call** `help-centre.get_article` `{"article_id": "KB-004"}`
   - **isError: false** → what the model read:

     ```text
     {
       "article_id": "KB-004",
       "title": "Troubleshooting AirFiber connectivity",
       "source_file": "troubleshooting_connectivity.md",
       "product_area": "troubleshooting",
       "last_updated": "2026-08-10",
       "text": "Troubleshooting AirFiber connectivity\nUse this article when the AirFiber connection is  …(truncated)
     ```

4. **model** final reply (1504 chars):

<details><summary>Show reply</summary>

> Hi [Customer Name],
> 
> Thank you for reaching out.
> 
> The information in article **KB‑004** (Troubleshooting AirFiber connectivity) states that a **blinking red LED** on the ONT does **not** indicate a simple router restart. It means:
> 
> | LED colour | Pattern | Meaning |
> |------------|---------|---------|
> | **Red** | **Blinking** | Fiber cut detected between your home and the exchange – a line‑fault ticket is required and a field‑engineer visit will be scheduled. |
> 
> (See KB‑004, “Router LED status reference”.)
> 
> Because the red light is blinking, restarting the router will not resolve the issue. Please open a **Line Fault ticket** so our engineering team can investigate the fiber cut and arrange a repair visit.
> 
> **How to raise the ticket**
> 
> 1. Log in to the AirFiber app or web portal.  
> 2. Go to **Support → Create Ticket**.  
> 3. Choose **“Line Fault – Fiber Cut”** as the issue type.  
> 4. Provide the ONT serial number (found on the device label) and a brief description of the symptom (blinking red LED).  
> 
> Once the ticket is submitted, you’ll receive a reference number (e.g., TCK‑1234) and an estimated time for a technician visit. We’ll keep you updated on the progress.
> 
> If you have already opened a ticket, please reply with the ticket ID so we can check its status for you.
> 
> We apologize for the inconvenience and appreciate your patience while we resolve this.
> 
> Best regards,  
> [Your Name]  
> AirFiber Support  
> 
> *Source: KB‑004 – “Troubleshooting AirFiber connectivity”, LED status table.*

</details>

## Transcript — before, unseeded (`evidence/error_before_unseeded.json`)

**Ticket:** A customer writes: 'Your help article KB-4 says a blinking red light just means I should restart the router. I restarted it five times and it is still red.' Check what article KB-4 actually says and draft the reply.

1. **model** decides to call `get_article` `{"article_id":"KB-4"}`

2. **tool_call** `help-centre.get_article` `{"article_id": "KB-4"}`
   - **isError: true** → what the model read:

     ```text
     Error executing tool get_article: Error 3
     ```

3. **model** decides to call `search_help_centre` `{"query":"KB-4","top_k":5}`

4. **tool_call** `help-centre.search_help_centre` `{"query": "KB-4", "top_k": 5}`
   - **isError: false** → what the model read:

     ```text
     {
       "query": "KB-4",
       "available_areas": [
         "account",
         "billing",
         "installation",
         "plans",
         "troubleshooting"
       ],
       "passages": [
         {
           "article_id": "KB-001",
           "source_file": "airfiber_plans.md",
           "section": "AirFiber broadband plans > AirFiber_1199_1M plan",
         …(truncated)
     ```

5. **model** decides to call `search_help_centre` `{"product_area":"troubleshooting","query":"blinking red light router","top_k":10}`

6. **tool_call** `help-centre.search_help_centre` `{"product_area": "troubleshooting", "query": "blinking red light router", "top_k": 10}`
   - **isError: false** → what the model read:

     ```text
     {
       "query": "blinking red light router",
       "available_areas": [
         "account",
         "billing",
         "installation",
         "plans",
         "troubleshooting"
       ],
       "passages": [
         {
           "article_id": "KB-004",
           "source_file": "troubleshooting_connectivity.md",
           "section": "Troubleshooting Air …(truncated)
     ```

7. **model** final reply (1098 chars):

<details><summary>Show reply</summary>

> Hi [Customer Name],
> 
> Thank you for reaching out.
> 
> The information in article **KB‑004** (Router LED status reference) states that a **blinking red LED** on the ONT does **not** indicate a simple restart is required. Instead, it means:
> 
> | LED colour | Pattern | Meaning |
> |------------|---------|---------|
> | **Red** | **Blinking** | Fiber cut detected between your home and the exchange |
> 
> The recommended action is to **raise a Line Fault ticket** so our field‑engineer team can investigate and resolve the fiber cut. Restarting the router will not clear this condition.
> 
> **Next steps**
> 
> 1. Open a Line Fault ticket via the AirFiber app or our support portal.  
> 2. Include the ONT serial number (found on the label) and a brief description of the blinking red LED.  
> 3. Our engineering team will schedule a visit and keep you updated on the progress.
> 
> If you need assistance creating the ticket, please let us know and we’ll be happy to help.
> 
> Best regards,  
> [Your Name]  
> AirFiber Support  
> 
> *Source: KB‑004 – “Router LED status reference” (blinking red = fiber cut, raise a Line Fault ticket).*

</details>

## Transcript — after, unseeded (`evidence/error_after_unseeded.json`)

**Ticket:** A customer writes: 'Your help article KB-4 says a blinking red light just means I should restart the router. I restarted it five times and it is still red.' Check what article KB-4 actually says and draft the reply.

1. **model** decides to call `get_article` `{"article_id":"KB-004"}`

2. **tool_call** `help-centre.get_article` `{"article_id": "KB-004"}`
   - **isError: false** → what the model read:

     ```text
     {
       "article_id": "KB-004",
       "title": "Troubleshooting AirFiber connectivity",
       "source_file": "troubleshooting_connectivity.md",
       "product_area": "troubleshooting",
       "last_updated": "2026-08-10",
       "text": "Troubleshooting AirFiber connectivity\nUse this article when the AirFiber connection is  …(truncated)
     ```

3. **model** final reply (1113 chars):

<details><summary>Show reply</summary>

> Hi [Customer Name],
> 
> Thank you for reaching out.
> 
> The information you quoted is not correct for a **blinking red** LED. According to our help article **KB‑004** the LED status table states:
> 
> | LED colour | Pattern | Meaning |
> |------------|---------|---------|
> | **Red** | **Blinking** | *Fiber cut detected between the home and the exchange* – a Line Fault ticket must be raised and a field‑engineer visit is required. |
> 
> A solid red LED, by contrast, indicates “No optical signal reaching the ONT” and suggests checking the fiber cable for sharp bends before raising a ticket.
> 
> Because your router’s LED is blinking red, restarting it will not resolve the issue. Please let us know if you’d like us to open a Line Fault ticket on your behalf, or you can submit one through the customer portal. Once the ticket is created, a technician will be dispatched to investigate the fiber cut.
> 
> If you have any further questions or need assistance opening the ticket, just reply to this message and I’ll be happy to help.
> 
> Best regards,  
> [Your Name]  
> AirFiber Support  
> 
> *Source: KB‑004 – “Router LED status reference”*

</details>

## Reproduce

```bash
cd backend
Q="A customer writes: 'Your help article KB-4 says ...' Check what article KB-4 actually says and draft the reply."
git checkout w9-server1+2 -- mcp_servers/help_centre/server.py   # before
python -m app.agents.week9.agent --seed-call get_article --seed-args '{"article_id": "KB-4"}' "$Q"
git checkout HEAD -- mcp_servers/help_centre/server.py            # after
python -m app.agents.week9.agent --seed-call get_article --seed-args '{"article_id": "KB-4"}' "$Q"
```
