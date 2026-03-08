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
Some more structured way of storing knowledge is required, eg unit_of_content (title, text, embedding, source (media name), type (mail, insta, ...), source_url, created_at, metadata (can be smm statistics or whatever useful)) and media table (i dont want to use the word competitor because this table and units of content include our own data too). in that spirit, knowledge entires should be renamed to unit_of_knowledge. what I do not like about this is that we will have multiple knowledge tables. it would make sense to have a single knowledge table with typing and categorizing. i guess that is indeed more optimal. the structure can be partially stored in metadata and partially refetched by source_url. so yeah, using unit of knowledge for everything. what do you think? 

