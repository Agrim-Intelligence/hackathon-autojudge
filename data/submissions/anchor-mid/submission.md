# StudyBuddyAI

team: anchor-mid (solo)

idea: study companion that takes a PDF (textbook chapter / lecture notes)
and generates flashcards + a 10-question quiz with explanations.

links:
- repo https://github.com/example/studybuddy-ai
- deployed https://studybuddy.streamlit.app  (sometimes goes to sleep on
  community cloud, may need a refresh)

what it does:
- upload pdf
- gpt extracts key concepts (single prompt, no tool calls)
- second prompt generates 10 mcq questions in json
- streamlit renders them with a "show explanation" toggle
- there's also a "make flashcards" button which is basically the same
  prompt but outputs a different json shape

stack: streamlit, python, openai (gpt-4o-mini), pypdf for parsing.

ai stuff: two prompts. no agentic loop. no tools. no retries. there is
some json parsing with a fallback to "sorry try again" which is technically
a guardrail i guess.

tests: none. there is a tests/ folder but it's empty.

evals: i ran it manually on three pdfs and it worked. no automated evals.

what doesn't work:
- long pdfs (>30 pages) blow the context. i truncate to first 12000 chars.
- math heavy pdfs render badly because pypdf strips equations.
- the quiz sometimes asks about content that wasn't in the pdf (model
  hallucinations). i did not fix this in time.
- no auth, anyone can use it, no rate limits.

things i wanted to do but didn't get to:
- chunked retrieval over pdf
- adaptive difficulty based on which questions the user got wrong
- export to anki

build log (mostly commits):
- 23-may  pdf upload + first prompt
- 23-may  quiz prompt
- 24-may  flashcards button + deploy to community cloud
- 24-may  ui polish, dark mode

attribution: started from the streamlit chat example, kept the layout.
copied a pypdf snippet from stackoverflow for the text extraction.

i used claude (the chat website, not in code) to draft the prompts and
debug pyhton errors.
