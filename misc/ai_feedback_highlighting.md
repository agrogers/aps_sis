1. What exactly is the unit you’re tagging?
Chunk on punctuation - so a chunk starts at the beginning of a sentence and finishes at a comma or semicolon or new line etc. Bigger than word level but smaller than sentence.

4. What happens when feedback spans non-contiguous text?
The LLM can return multiple chunk ids for a particular point.

5. How precise does highlighting need to be?
Per chunk

6. How will you prevent hallucinated IDs?
I like your "pre-chunk" the student response. So they only return chunk ids

7. How tightly is this coupled to your rubric system?
Not tightly initially. But if the LLM is good, it should naturally identify elements and highlight them.

8. What does the UI interaction look like?
Side-by-side. Response on the left, feedback on the right. Perhaps the feedback is underlined using different colours. When the user clicks the feedback the relevant chunks are highlighted in the response.

9. What about overlapping feedback?
Feedback has associated chunks which can overlap with other feedback. Only show one feedback detail at one time so its ok. Chunk do not need to be contiguous. Just highlight whatever chunks are relevant.


“HTML + sidecar mapping”
eg {
  "html": "<h3>Feedback</h3><ul><li id='f1'>Photosynthesis does not occur in roots.</li><li id='f2'>Good understanding of water absorption.</li></ul>",
    "type": "concept_error",
    "severity": "major",
  "links": [
    { "feedback_id": "f1", "chunk_ids": ["c1"] },
    { "feedback_id": "f2", "chunk_ids": ["c2"] }
  ]
}
Use this to keep the beautiful formatting that LLMs can return - headings, bullets, emojis, colouring etc. 
---
How about this:
1. The HTML student response is tagged with chunk IDs
2. Those chunks are converted into a json format and sent to the AI
3. The AI marks the response and returns HTML
5. My JS hooks into that button, and when clicked updates chunk classes in the response.

