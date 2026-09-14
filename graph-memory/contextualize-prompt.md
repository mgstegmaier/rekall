# Situate wiki chunks in their page

contextualize.py runs this prompt over one page and stores the result itself.
Do not write, save, or create any file. Print one JSON object and nothing else.

---

Below is one page from a personal wiki, then the sections of that page that need
context. Search indexes each section on its own, without the page around it, so a
section called "Next steps" arrives with no sign of what it is about.

For each listed section, write one or two sentences that situate it within the
page, for the purpose of improving search retrieval of that section:

- Name the page's subject, spelled as the page's title spells it, in the first sentence.
- Say what the section itself covers: the decision, the number, the state, the step.
- Name the things the section concerns, using the names as written on the page.
  The wikilink targets found in a section are listed beside it.
- Plain declarative sentences. No "this chunk", no "this section", no preamble,
  no markdown, no invented facts.

Reply with one JSON object: the key is the section heading exactly as it was
given, the value is the one or two sentences. Every listed section gets a key,
and nothing appears outside the object.

Example reply:

    {"Next steps": "Doc extraction is a project page for pulling structured fields out of scanned PDFs. Its next steps list the remaining work on the parser and the evaluation harness."}

---

<paste the page and its sections here>
