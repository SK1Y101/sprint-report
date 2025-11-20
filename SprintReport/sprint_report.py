import argparse
import re
import sys

from collections import Counter
from dataclasses import dataclass
from jira import JIRA, JIRAError
from natsort import natsorted
from typing import Optional

from SprintReport.jira_api import jira_api

jira_server = ""

def get_bug_id(summary: str) -> str:
    "Extract the bug id from a jira title which would include LP#"
    if search := re.search(r"LP#(\d+)", summary):
        return search.group(1)
    return ""

def key_to_md(key: str) -> str:
    global jira_server
    return f"[{key}]({jira_server}/browse/{key})"

@dataclass
class JiraIssue:
    key: str
    category: str
    status: str
    parent: str
    summary: str
    epic: str
    epic_name: Optional[str] = "No epic"
    assignee: Optional[str] = None

    __assignee_short__: Optional[str] = None

    @property
    def summary_with_bug_link(self) -> str:
        if bug_id := get_bug_id(self.summary):
            bug = f"LP#{bug_id}"
            link = f"https://pad.lv/{bug_id}"
            return re.sub(bug, f"[{bug}]({link})", self.summary)
        return self.summary
    
    @property
    def markdown_key(self) -> str:
        return key_to_md(self.key)
    
    def update_assignee(self, assignee_mapping: dict[str, str]) -> None:
        if (assignee := self.assignee):
            self.__assignee_short__ = assignee_mapping.get(assignee)

    @property
    def render_assignee(self) -> str:
        return self.__assignee_short__ or self.assignee or ""
    
    @property
    def render_issue(self) -> str:
        if "LP#" in self.summary:
            return " : ".join(filter(None,
                [
                    f" - {self.summary_with_bug_link}",
                    self.render_assignee
                ]
            ))
        return " : ".join(filter(None,
            [
                f" - [{self.status}] {self.category}",
                self.markdown_key,
                self.summary,
                self.render_assignee
            ]
        ))


def find_issue_in_jira_sprint(jira_api, project: str, sprint: str) -> list[JiraIssue]:
    if not jira_api or not project:
        return {}

    # Get JIRA issues in batch of 50
    issue_index = 0
    issue_batch = 50

    found_issues: list[JiraIssue] = []

    while True:
        start_index = issue_index * issue_batch
        request = f"project = {project} " \
            f"AND cf[10020] = \"{sprint}\" " \
            f"AND status in (Done, 'In Progress', 'In review', 'To do') ORDER BY 'Epic Link'"
        issues = jira_api.search_issues(request, startAt=start_index)

        if not issues:
            break

        issue_index += 1
        epics = {}
        # For each issue in JIRA with LP# in the title
        for issue in issues:
            summary = issue.fields.summary
            try:
                parent_key = issue.fields.parent.key
            except AttributeError:
                parent_key = ""
            epic_link = issue.fields.customfield_10014
            if epic_link not in epics:
                try:
                    epics[epic_link] = jira_api.issue(epic_link).fields.summary
                except JIRAError:
                    epics[epic_link] = "No epic"
            
            found_issues.append(JiraIssue(
                key = issue.key,
                category = issue.fields.issuetype.name,
                status = issue.fields.status.name,
                epic = epic_link,
                epic_name = epics[epic_link],
                parent = parent_key,
                summary = summary,
                assignee = assignee.displayName if (assignee := issue.fields.assignee) else None
            ))

    return found_issues

def find_unique_assignee_names(issues: list[JiraIssue], collapse_surname: bool=True) -> dict[str, str]:
    """
    Return a unique set of all names. if collapse_surname, each name is one of:
    Firstname
    Firstname S.
    Firstname Surname
    
    where the smallest is selected to preserve uniqueness.
    """
    
    all_assignees = {issue.assignee for issue in issues if issue.assignee}
    if not collapse_surname:
        return {name: name for name in all_assignees}
    
    def to_name(name: str) -> tuple[str, str]:
        names = name.split(maxsplit=1)
        return names[0], (names[1:] or [""])[0]

    # For simplicity, We assume the firstname is a single word, and the surname is all other words.
    # Will need to be extended for further inclusivity.
    first_names = [name.split()[0] for name in all_assignees]
    surname_initials = [
        (names[0], names[1][0])
        for name in all_assignees
        if (names := to_name(name))
    ]

    first_name_count = Counter(first_names)
    surname_inital_count = Counter(surname_initials)

    unique_names = {
        name: (
            first_name
            if first_name_count[first_name] == 1
            else (
                f"{first_name} {surname[0]}"
                if surname
                and surname_inital_count[(first_names, surname_inital_count[0])]
                == 1
                else name
            )
        )
        for name in all_assignees
        if (names := to_name(name))
        and (first_name := names[0])
        and (surname := names[1])
    }

    return unique_names



def print_jira_report(jira_api, project: str, issues: list[JiraIssue], assignee_names: dict[str, str]) -> None:
    if not issues:
        return
    
    global sprint
    parent = ""
    epic = ""
    print(f"# {project} {sprint} report")

    issues: list[JiraIssue] = natsorted(issues, key=lambda i: (i.parent, i.epic, i.key))
    for issue in issues:
        if issue.parent != parent:
            parent = issue.parent
            parent_summary = jira_api.issue(parent).fields.summary
            print(f"\n## {key_to_md(parent)}: {parent_summary}")
        if issue.epic != epic:
            epic = issue.epic
            if epic:
                if epic != parent: # don't print top-level epics twice
                    print(f"\n### {key_to_md(epic)}: {issues[issue]["epic_name"]}")
            else:
                print("\n### Issues without an epic")
        
        if assignee_names:
            issue.update_assignee(assignee_names)

        print(issue.render_issue)


def main(args=None) -> None:
    global jira_server
    global sprint
    parser = argparse.ArgumentParser(
        description=
            "A script to return a a Markdown report of a Jira Sprint"
    )

    parser.add_argument("project", type=str, help="key of the Jira project")
    parser.add_argument("sprint", type=str, help="name of the Jira sprint")
    parser.add_argument(
        "--skip-names",
        action="store_true",
        help="If set, the final report will *not* contain the names of people assigned to each issue."
    )

    opts = parser.parse_args(args)

    try:
        api = jira_api()
    except ValueError as e:
        print(f"ERROR: Cannot initialize Jira API: {e}", file=sys.stderr)
        sys.exit(1)

    jira_server = api.server

    jira = JIRA(api.server, basic_auth=(api.login, api.token))

    sprint = opts.sprint
    # Create a set of all Jira issues completed in a given sprint
    issues = find_issue_in_jira_sprint(jira, opts.project, sprint)
    assignees = {} if args.skip_names else find_unique_assignee_names(issues, collapse_surname=True) 

    print("Found {} issue{} in JIRA\n".format(
        len(issues),"s" if len(issues)> 1 else "")
    )

    print_jira_report(jira, opts.project, issues, assignees)

# =============================================================================
