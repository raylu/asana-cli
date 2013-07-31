#!/usr/bin/env python
# vim: set sw=4 ts=4:

from collections import defaultdict
import fcntl
import operator
import os.path
import readline
import struct
import subprocess
import sys
import termios
import textwrap

import requests
from termcolor import colored

class API(object):
    def __init__(self, api_key):
        self.api_key = api_key
        self.rs = requests.Session()

    def __make_req(self, *path, **params):
        url = 'https://app.asana.com/api/1.0/' + '/'.join(path)
        r = self.rs.get(url, params=params, auth=(self.api_key, '')).json()
        if 'errors' in r:
            raise Exception(r['errors'])
        return r['data']

    def workspaces(self):
        return self.__make_req('workspaces')
    def projects(self, workspace_id):
        projects = self.__make_req('workspaces', str(workspace_id), 'projects', opt_fields='name,archived,modified_at')
        projects = filter(lambda p: not p['archived'], projects)
        projects.sort(key=operator.itemgetter('modified_at'), reverse=True)
        return projects
    def tasks(self, project_id=None, workspace_id=None):
        if project_id is not None:
            tasks = self.__make_req('projects', str(project_id), 'tasks', opt_fields='name,completed,assignee_status')
        elif workspace_id is not None:
            tasks = self.__make_req('workspaces', str(workspace_id), 'tasks', assignee='me', opt_fields='name,completed,assignee_status')
        else:
            raise ValueError('must pass one of project_id, workspace_id')
        if project_id is not None:
            tasks.sort(key=operator.itemgetter('completed'), reverse=True)
            sorted_tasks = tasks
        else:
            by_status = defaultdict(list)
            for t in tasks:
                if t['completed']:
                    by_status['completed'].append(t)
                else:
                    by_status[t['assignee_status']].append(t)
            sorted_tasks = by_status['completed'] + by_status['inbox'] + \
                by_status['today'] + by_status['upcoming'] + by_status['later']
        return sorted_tasks
    def task(self, task_id):
        task = self.__make_req('tasks', str(task_id))
        stories = self.__make_req('tasks', str(task_id), 'stories')
        task['stories'] = stories
        return task

class Shell(object):
    WORKSPACES = 0
    PROJECTS = 1
    TASKS = 2
    TASK = 3

    def __init__(self, api_key):
        self.api = API(api_key)
        self.pwd = []
        self.path = [None, None, None, None] # workspace, project, tasks, task

        readline.set_completer(self.complete)
        readline.set_completer_delims('')
        readline.parse_and_bind('tab: complete')

        self.path[self.WORKSPACES] = self.api.workspaces()

    def run(self):
        self.display()
        try:
            while True:
                if self.prompt():
                    self.display()
        except EOFError:
            print

    @staticmethod
    def terminal_size():
        sizes = fcntl.ioctl(0, termios.TIOCGWINSZ, struct.pack('HHHH', 0, 0, 0, 0))
        height, width, _, _ = struct.unpack('HHHH', sizes)
        return height, width

    def display(self):
        pwd_len = len(self.pwd)
        if pwd_len == self.WORKSPACES:
            workspaces = map(operator.itemgetter('name'), self.path[self.WORKSPACES])
            self.print_col(workspaces)
        elif pwd_len == self.PROJECTS:
            projects = ['me'] + map(operator.itemgetter('name'), self.path[self.PROJECTS])
            self.print_col(projects)
        elif pwd_len == self.TASKS:
            last_status = None
            for t in self.path[self.TASKS]:
                if t['completed']:
                    print colored(u' \u2713 ', 'green'),
                    print colored(t['name'], 'grey', attrs=['bold'])
                else:
                    if self.pwd[self.PROJECTS] == 'me' and t['assignee_status'] != last_status:
                        print colored(t['assignee_status'], 'grey')
                        last_status = t['assignee_status']
                    if t['name'].endswith(':'):
                        print colored(t['name'], 'yellow')
                    else:
                        print '    ' + t['name']
        elif pwd_len == self.TASK:
            task = self.path[self.TASK]
            out = []
            out.append(colored(task['name'], attrs=['bold']))
            if task['completed']:
                out.append(colored('completed', 'green', attrs=['bold']))
            if task['assignee']:
                out.append(colored('assignee: ', 'yellow') + task['assignee']['name'])
            else:
                out.append(colored('assignee: ', 'yellow') + 'none')
            out.append(colored('notes: ', 'yellow') + task['notes'])
            if task['due_on']:
                out.append(colored('due on: ', 'yellow') + task['due_on'])
            terminal_height, terminal_width = self.terminal_size()
            out.append(colored('comments:', 'yellow'))
            for s in task['stories']:
                if s['type'] == 'system':
                    line = '{} {} {}'.format(s['created_by']['name'], s['text'], s['created_at'])
                    out.append(colored(line, 'magenta'))
                elif s['type'] == 'comment':
                    out.append(colored('{} {}'.format(s['created_by']['name'], s['created_at']), 'blue'))
                    for line in s['text'].splitlines():
                        wrapped = textwrap.fill(line,
                            min(terminal_width, 100), replace_whitespace=False,
                            initial_indent='    ', subsequent_indent='    ')
                        out.append(wrapped)
                else:
                    raise RuntimeError('unhandled story type: ' + s['type'])
            out.append(colored('followers:', 'yellow'))
            for f in task['followers']:
                out.append('    ' + f['name'])

            out_str = '\n'.join(out).encode('utf-8')
            print out_str # always print to stdout
            if out_str.count('\n') >= terminal_height: # there can be newlines in each element so we must count
                less = subprocess.Popen(['less', '--RAW-CONTROL-CHARS'], stdin=subprocess.PIPE)
                less.stdin.write(out_str)
                less.stdin.close()
                less.wait()
        else:
            raise RuntimeError('unhandled working directory depth')

    def print_col(self, strings):
        strings_len = len(strings)
        col_width = max(map(len, strings)) + 2
        terminal_width = self.terminal_size()[1]
        cols = max(terminal_width / col_width, 1)
        rows = max(strings_len / cols, 1)
        for r in xrange(rows):
            for c in xrange(cols):
                index = c * rows + r
                if index > strings_len - 1:
                    break
                print strings[index].ljust(col_width),
            print

    def prompt(self):
        prompt = []
        max_len = 12
        for elem in self.pwd:
            if elem == 'me':
                prompt.append(elem)
            elif len(elem['name']) > max_len:
                prompt.append(elem['name'][:max_len-3] + u'\u2026')
            else:
                prompt.append(elem['name'])
        prompt_str = (', '.join(prompt) + '> ').encode('utf-8')
        line = raw_input(colored(prompt_str, 'blue', attrs=['bold']))
        pwd_len = len(self.pwd)
        split = line.split(' ', 1)
        command = split[0]
        if command == 'cl':
            if len(split) == 1:
                print 'you must specify a "directory" to move to'
                return False
            elif split[1] == '..':
                self.pwd.pop()
            elif pwd_len == self.WORKSPACES:
                for w in self.path[self.WORKSPACES]:
                    if w['name'] == split[1]:
                        self.pwd.append(w)
                        projects = self.api.projects(w['id'])
                        self.path[self.PROJECTS] = projects
                        break
                else:
                    print 'could not find that workspace'
            elif pwd_len == self.PROJECTS:
                if split[1] == 'me':
                    self.pwd.append('me')
                    tasks = self.api.tasks(workspace_id=self.pwd[self.WORKSPACES]['id'])
                    self.path[self.TASKS] = tasks
                else:
                    for p in self.path[self.PROJECTS]:
                        if p['name'] == split[1]:
                            self.pwd.append(p)
                            tasks = self.api.tasks(project_id=p['id'])
                            self.path[self.TASKS] = tasks
                            break
            elif pwd_len == self.TASKS:
                for t in self.path[self.TASKS]:
                    if t['name'] == split[1]:
                        self.pwd.append(t)
                        task = self.api.task(t['id'])
                        self.path[self.TASK] = task
                        break
                else:
                    print 'could not find that task'
            elif pwd_len == self.TASK:
                return False
            else:
                raise RuntimeError('unhandled working directory depth')
            return True
        else:
            print 'unrecognized command'
            return False

    def complete(self, text, state):
        if not text.startswith('cl ') or len(text) < 4:
            return
        ltext = text[3:].lower()
        match = 0
        search_list = self.path[len(self.pwd)]
        for item in search_list:
            if ltext in item['name'].lower():
                if match == state:
                    return 'cl ' + item['name']
                match += 1

if __name__ == '__main__':
    if os.path.exists('api_key'):
        with open('api_key', 'r') as f:
            api_key = f.read()
    else:
        print('could not find api_key file in current directory; enter key to be saved to file')
        api_key = raw_input('api key: ')
        with open('api_key', 'w') as f:
            f.write(api_key)
        print('saved api_key\n')
    shell = Shell(api_key)
    if len(sys.argv) > 1:
        url = sys.argv[1]
        path = map(int, url[22:].split('/'))
        workspace = shell.path[shell.WORKSPACES][path[0]]
        shell.pwd.append(workspace)
        shell.path[shell.PROJECTS] = shell.api.projects(workspace['id'])
        for p in shell.path[shell.PROJECTS]:
            if p['id'] == path[shell.PROJECTS]:
                shell.pwd.append(p)
                shell.path[shell.TASKS] = shell.api.tasks(project_id=p['id'])
                break
        for t in shell.path[shell.TASKS]:
            if t['id'] == path[shell.TASKS]:
                shell.pwd.append(t)
                shell.path[shell.TASK] = shell.api.task(t['id'])
                break
    shell.run()
