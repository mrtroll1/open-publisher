# Making brain smarter through context

## What?

Important context bits that currently are not part of the system is:
    Our social media (most just announcing new articles but we want to make them more fun)
    Resources of our competitors (web & social nedia)
    Conversations from various chats
    Zoom calls

I want the service to be aware of all of that. Let's split that into two categories: 
    External and Internal
These are categories only relevant for this plan and discussion, not to the eventual implementation or domain logic

### External

This is about SM & competitors. 
The behavaior I want is roughly: 
    'Here's what our competitors have been busy with today: ...'
    'I think our social media lack... Here is what guys at ... do: ...'
    'This media ... produced that pice of content ... Didn't we have an interview with the same person?'
    'The numbers is our instagram have dropped. How about ...?'

### Internal

This is about work chat histories & zoom calls.
The behavior I want is roughly:
    A one-time /env_summarize - go trhough chat history (in tg - topic-specific) and extract and store useful knowledge into knowledge entries
    Zoom: maybe just tell it to extract knowledge and remember smth from the transcript? (using existing pipes)
What is needed: 
    A slightly more flexible knowledge domain approach, perhaps. Issue: we create knowledge and knowledge domains on the fly, but do we update the allowed domains of environemnts or users? Even if we do, it seems like a lot of hustle. 

## How?

Internal (described use-cases) is relatively straightforward - knowledge is all here and easy to parse (tg chat, zoom transcript)
BY it's content this knowledge fits nicely into knowledge entries structure - natural language meanings.

For both external to work, three rpoblems needs to be solved: 
    how to get the knowledge? how to store it? how to retrieve it? 

Scraping insta / telegram / mails? 
Some more structured way of storing knowledge is required, eg unit_of_content (title, text, embedding, source (media name), type (mail, insta, ...), source_url, created_at, metadata (can be smm statistics or whatever useful)) and media table (i dont want to use the word competitor because this table and units of content include our own data too). in that spirit, knowledge entires should be renamed to units_of_knowledge. what I do not like about this is that we will have multiple knowledge tables. it would make sense to have a single knowledge table with typing and categorizing. i guess that is indeed more optimal. the structure can be partially stored in metadata and partially refetched by source_url. so yeah, using unit of knowledge for everything. what do you think? 

//

doesnt click with me. i do not want a setup that only works for me as admin. you're right about domains being an access control     mechanism, not relevance. can we let this judgement be automatic tho? this knowledge domain is gonna be available to ... for each created knowledge domain? but hm no that's also bad. access control is preferably on unit level, no on dmoain level. what about explicit permissions for each unit of knowledge - owned by user / for admin and editors / for admins only / ... . simillar to how it works with tools. so for example /env_summarize goes through and creates new units of knowledge and perhaps new domains, this nice structured output of what to store and does not have to think about permissions - it will be available to anyone within this environment and to admins. but if for example brain remembers some contractor payment data from the conversation with a contractor, it should decide to make it contractor-owned but also of accessible to admins. so this permissions step will the first filter. nothing to do with domains or permissions on the environemnts themselves. so permission lives on the object - just like with the tools. opinions? solid or actually bad? i am worried that retrieval will be slow and painful. but on the other hand it does make sense - ask knowledge repo - hey, which knowledge do i have access too. so the idea is that llm could reference and use any knowledge rag and it sees fit from all the knowledge allowed, not constraint by hard-coded domains. that sounds smarter than what we have now.

then there is also the question of: permission first or rag first? almost certainly permission first. 

what about knowledge domains as they exist now? ceratinly could be usefull for topic categorization and relevance-search. 