#!/usr/bin/env python3
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
    BASE_URL = 'https://app.asana.com/api/1.0/'

    def __init__(self, api_key):
        self.api_key = api_key
        self.rs = requests.Session()

    def __make_req(self, verb, path, params=None, data=None):
        url = self.BASE_URL + '/'.join(path)
        r = self.rs.request(verb, url, params=params, data=data, auth=(self.api_key, '')).json()
        if 'errors' in r:
            raise Exception(r['errors'])
        return r['data']
    def __get(self, *path, **params):
        return self.__make_req('get', path, params=params)
    def __put(self, *path, data):
        return self.__make_req('put', path, data=data)
    def __post(self, *path, data):
        return self.__make_req('post', path, data=data)

    def workspaces(self):
        return self.__get('workspaces')
    def projects(self, workspace_id):
        projects = self.__get('workspaces', str(workspace_id), 'projects',
                archived=False, opt_fields='name,archived,modified_at')
        projects.sort(key=operator.itemgetter('modified_at'), reverse=True)
        return projects
    def tasks(self, project_id=None, workspace_id=None):
        if project_id is not None:
            tasks = self.__get('projects', str(project_id), 'tasks', opt_fields='name,completed,assignee_status')
        elif workspace_id is not None:
            tasks = self.__get('workspaces', str(workspace_id), 'tasks', assignee='me', opt_fields='name,completed,assignee_status')
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
    def task(self, task_id, put_data=None):
        if put_data is None:
            task = self.__get('tasks', str(task_id))
            stories = self.__get('tasks', str(task_id), 'stories')
            task['stories'] = stories
        else:
            task = self.__put('tasks', str(task_id), data=put_data)
        return task
    def stories(self, task_id, post_data):
        story = self.__post('tasks', str(task_id), 'stories', data=post_data)
        return story

class Shell(object):
    WORKSPACES = 0
    PROJECTS = 1
    TASKS = 2
    TASK = 3

    def __init__(self, api_key):
        self.api = API(api_key)
        self.pwd = []
        self.path = [None, None, None, None] # workspace, project, tasks, task

        readline.set_completer(self.tab_complete)
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
            workspaces = list(map(operator.itemgetter('name'), self.path[self.WORKSPACES]))
            self.print_col(workspaces)
        elif pwd_len == self.PROJECTS:
            projects = ['me'] + list(map(operator.itemgetter('name'), self.path[self.PROJECTS]))
            self.print_col(projects)
        elif pwd_len == self.TASKS:
            last_status = None
            for t in self.path[self.TASKS]:
                if t['completed']:
                    print(colored(' \u2713 ', 'green'), end='')
                    print(colored(t['name'], 'grey', attrs=['bold']))
                else:
                    if self.pwd[self.PROJECTS] == 'me' and t['assignee_status'] != last_status:
                        print(colored(t['assignee_status'], 'grey'))
                        last_status = t['assignee_status']
                    if t['name'].endswith(':'):
                        print(colored(t['name'], 'yellow'))
                    else:
                        print('    ' + t['name'])
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

            out_str = '\n'.join(out)
            print(out_str) # always print to stdout
            if out_str.count('\n') >= terminal_height: # there can be newlines in each element so we must count
                less = subprocess.Popen(['less', '--RAW-CONTROL-CHARS'], stdin=subprocess.PIPE)
                less.stdin.write(out_str.encode('utf-8'))
                less.stdin.close()
                less.wait()
        else:
            raise RuntimeError('unhandled working directory depth')

    def print_col(self, strings):
        strings_len = len(strings)
        col_width = max(map(len, strings)) + 2
        terminal_width = self.terminal_size()[1]
        cols = max(terminal_width // col_width, 1)
        rows = max(strings_len // cols, 1)
        for r in range(rows):
            for c in range(cols):
                index = c * rows + r
                if index > strings_len - 1:
                    break
                print(strings[index].ljust(col_width), end='')
            print()

    def prompt(self):
        prompt = []
        max_len = 12
        for elem in self.pwd:
            if elem == 'me':
                prompt.append(elem)
            elif len(elem['name']) > max_len:
                prompt.append(elem['name'][:max_len-3] + '\u2026')
            else:
                prompt.append(elem['name'])
        prompt_str = (', '.join(prompt) + '> ')
        line = input(colored(prompt_str, 'blue', attrs=['bold']))
        split = line.split(' ', 1)
        command = split[0]
        if command == 'cl':
            return self.command_cl(split)
        elif command == 'ls':
            return self.command_ls(split)
        elif command == 'done':
            return self.command_done(split)
        elif command == 'comment':
            return self.command_comment(split)
        else:
            print('unrecognized command')
            return False

    def command_cl(self, split):
        pwd_len = len(self.pwd)
        if len(split) == 1:
            print('you must specify a "directory" to move to')
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
                print('could not find that workspace')
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
                print('could not find that task')
        elif pwd_len == self.TASK:
            return False
        else:
            raise RuntimeError('unhandled working directory depth')
        return True

    def command_ls(self, split):
        pwd_len = len(self.pwd)
        if pwd_len == self.WORKSPACES:
            workspaces = self.api.workspaces()
            self.path[self.WORKSPACES] = workspaces
        elif pwd_len == self.PROJECTS:
            projects = self.api.projects(self.pwd[self.WORKSPACES]['id'])
            self.path[self.PROJECTS] = projects
        elif pwd_len == self.TASKS:
            project = self.pwd[self.PROJECTS]
            if project == 'me':
                tasks = self.api.tasks(workspace_id=self.pwd[self.WORKSPACES]['id'])
            else:
                tasks = self.api.tasks(project_id=project['id'])
            self.path[self.TASKS] = tasks
        elif pwd_len == self.TASK:
            task = self.api.task(self.path[self.TASK]['id'])
            self.path[self.TASK] = task
        else:
            raise RuntimeError('unhandled working directory depth')
        return True

    def command_done(self, split):
        if len(self.pwd) != self.TASK:
            print('must be on a task')
            return False
        task = self.path[self.TASK]
        stories = task['stories']
        put_data = {
            'completed': not task['completed']
        }
        task = self.api.task(task['id'], put_data)
        task['stories'] = stories
        self.path[self.TASK] = task
        return True

    def command_comment(self, split):
        filename = 'comment'
        with open(filename, 'w') as f:
            pass
        editor = subprocess.Popen([os.environ['EDITOR'], filename])
        editor.wait()
        with open(filename, 'r') as f:
            comment = f.read().strip()
        os.unlink(filename)
        if not comment:
            print('ignoring empty comment')
            return False
        task = self.path[self.TASK]
        story = self.api.stories(task['id'], {'text': comment})
        task['stories'].append(story)
        return True

    def tab_complete(self, text, state):
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
        path = list(map(int, url[22:].split('/')))
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
