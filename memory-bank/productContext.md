# Product Context — APEX

## User Roles
- **Teachers/Managers**: Create resources, manage hierarchies, grade submissions, use AI marking
- **Students**: View assigned resources, submit work, view feedback
- **Admins**: Configure subjects, categories, AI models, system settings

## Core Workflows

### Resource Management
1. Teacher creates a resource (homework, exam, lesson)
2. Resources linked hierarchically via `parent_ids` / `child_ids`
3. Each resource has optional: question, answer, notes, lesson plan
4. Notes support inheritance via `has_notes='use_parent'` selection
5. Resources tagged for hierarchy display via `show_in_hierarchy` boolean

### Submission & Grading
1. Resources assigned to students → creates `aps.resource.task`
2. Students submit via `aps.resource.submission`
3. Teachers mark submissions manually or via AI
4. AI marking uses configurable models with prompt templates

### Course Explorer
1. Teachers browse course content via split-pane view
2. Left pane: hierarchical tree filtered by subject category
3. Right pane: unified content viewer with formatted HTML notes
4. Content ordered by tree traversal (depth-first, sequence-based)
5. Bidirectional scroll sync between tree and content

## Data Relationships
```
aps.subject.category
  └── aps.subject
        └── aps.resources (subjects M2M)
              ├── child_ids → aps.resources (linked)
              ├── supporting_resource_ids → aps.resources
              ├── parent_ids → aps.resources
              └── aps.resource.task → aps.resource.submission