"""Lift generated transport code into interfaces without changing model events.

The registry is per generation. It contains no application names or paths.
"""
from __future__ import annotations
import re

class HttpInterfaceRegistry:
    def __init__(self):
        self.entries = []

    def add(self, source, parameters, arguments, legacy_story, *, operation=None,
            local_prelude='', return_expression=None, story_prefix='', story_suffix=';'):
        name = 'sbtHttp_' + str(len(self.entries) + 1)
        invocation = name + '(' + ','.join(arguments) + ')'
        story = story_prefix + invocation + story_suffix
        body = local_prelude + source
        if return_expression is not None:
            body += '\nreturn ' + return_expression + ';'
        definition = 'function ' + name + '(' + ','.join(parameters) + ') {\n' + body + '\n}\n'
        self.entries.append({'name': name, 'definition': definition,
                             'story_call': story, 'legacy_story': legacy_story,
                             'operation': operation})
        return story

    def render(self):
        if not self.entries:
            return ''
        return '\n// Generated transport interfaces. Stories own scheduling; interfaces own HTTP.\n' + ''.join(entry['definition'] for entry in self.entries)

    def restore_legacy_story(self, stories):
        """Exact source comparison aid; never used for execution."""
        for entry in self.entries:
            current = stories
            def restore(match):
                prefix = current[current.rfind('\n', 0, match.start()) + 1:match.start()]
                indentation = prefix if not prefix.strip() else ''
                return entry['legacy_story'].replace('\n', '\n' + indentation)
            stories = re.sub(re.escape(entry['story_call']), restore, current)
        return stories
