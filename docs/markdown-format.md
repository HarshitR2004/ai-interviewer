# Authoritative Markdown format

The demo saves exactly `resume.pdf`, `persona.md`, and `interview-plan.md` for each
completed candidate under `DATA_DIR/demo/candidates/<candidate_id>/`. No JSON sidecars,
YAML frontmatter, manifests, checksums, or hidden machine payloads are required.

`persona.md` owns all CandidateProfile fields. `interview-plan.md` owns InterviewPlan,
InterviewSettings, and the complete job description. Replanning reuses the persona and
atomically replaces only the plan document. Candidate identity comes from its directory.

## Syntax rules

- Encoding is UTF-8. LF and CRLF document line endings are accepted and read as LF.
- Headings, their order, and their capitalization are fixed as shown below. Required
  headings cannot be omitted or repeated. Additional prose outside fields is rejected.
- Repeated groups are numbered consecutively from 1: Skill Group, Project, Source, Section.
- Scalar values use `> ` followed by text. Every continuation line is also prefixed.
  An empty scalar is one line containing only `>`. Do not wrap or trim field text.
- Lists use `- ` followed by text. Multiline item continuations start with exactly two
  added spaces. An empty string item is `- `; an empty continuation is two spaces.
- Empty lists and empty repeated-group collections are represented by `No entries.`.
- Null Project ID uses unquoted `Not project-specific.`. A real string with that text is
  quoted like any scalar and must reference a profile project ID.
- Markdown syntax within values is content, not structure. A heading inside a quoted
  scalar or indented list continuation is preserved. Blockquotes and bullets make those
  boundaries explicit; no backslash unescaping or Markdown-to-HTML conversion occurs.
- Blank separator lines may separate structural blocks. Blank lines inside values must
  use their blockquote/list prefix. Whitespace-only scalar/list lines are preserved.
- Duplicate skill categories or collection-source keys are invalid. Profile project IDs
  must be unique and source references must be valid. Unknown project IDs, duplicate
  questions, missing competency coverage, invalid durations/settings, and inconsistent
  totals are rejected when loading plans.
- A plan contains one focused base question per section. Settings duration is 15–120
  minutes. Fields for weak, adequate, and strong scoring guidance are all required.

This is a constrained, editable Markdown format rather than support for arbitrary
Markdown layouts. Rendering/parsing is deterministic and makes no model requests.
Unsupported edits return a document-format error; documents are never silently repaired
or overwritten on read. Preserve the headings when editing by hand.

## Complete persona example

```markdown
# Candidate Profile

## Identity

### Name

> Example Candidate

## Background

> Python developer

## Education

No entries.

## Experience

No entries.

## Skills

### Skill Group 1

#### Category

> Languages

#### Skills

- Python

## Projects

### Project 1

#### ID

> p1

#### Name

> Booking API

#### Purpose

> Book slots

#### Technologies

- Python

#### Contributions

- Built the API

#### Technical Details

- PostgreSQL

#### Source References

- resume

## Discussion Topics

- Concurrency

## Source References

- resume

## Collection Status

No entries.

```

All profile sections are mandatory, including empty Education, Experience, Skills,
Projects, Discussion Topics, Source References, and Collection Status. Skills may contain
multiple numbered categories, and Collection Status multiple numbered source/status pairs.

## Complete interview example

```markdown
# Interview Plan

## Role

> Software engineer

## Interview Settings

### Duration Minutes

> 45

### Seniority

> junior

## Job Description

> Build Python APIs with database design and testing.

## Required Competencies

- API design
- Testing

## Sections

### Section 1

#### Title

> API design

#### Competency

> API design

#### Duration Minutes

> 25

#### Question

> How would you prevent duplicate bookings?

#### Candidate Context

> Booking API

#### Project ID

> p1

#### Follow-ups

- What changes under concurrent requests?

#### Strong Answer Signals

- Explains tradeoffs

#### Scoring Guidance

##### Weak

> Unsupported guess with no reasoning.

##### Adequate

> A working approach with basic reasoning.

##### Strong

> Justified tradeoffs with failure handling.

### Section 2

#### Title

> Testing

#### Competency

> Testing

#### Duration Minutes

> 20

#### Question

> How would you test booking failures?

#### Candidate Context

> Booking API

#### Project ID

> p1

#### Follow-ups

- What changes under concurrent requests?

#### Strong Answer Signals

- Explains tradeoffs

#### Scoring Guidance

##### Weak

> Unsupported guess with no reasoning.

##### Adequate

> A working approach with basic reasoning.

##### Strong

> Justified tradeoffs with failure handling.

```

Repeat the complete section block for each required competency. Do not place a second
base question inside a section. The job description is stored in full as a multiline
blockquote, not summarized. The schema does not generate or persist numeric candidate scores.

## Multiline and empty examples

A scalar containing headings and a blank line:

```markdown
## Background

> First paragraph.
>
> ## This is content, not a new document heading
```

A list item with a continuation and an empty item:

```markdown
- First line
  Continued text
- 
```

`documents.py` owns the profile/plan mapping; `common/markdown.py` provides the small
Reader/Writer primitives. Unit tests verify the exact model round trips and malformed cases.
