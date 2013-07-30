#!/usr/bin/env python
# vim: set sw=4 ts=4:

from fabric import colors
import operator
import os.path
import requests
import readline

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
        return self.__make_req('workspaces', str(workspace_id), 'projects')
    def tasks(self, project_id=None, workspace_id=None):
        if project_id is not None:
            tasks = self.__make_req('projects', str(project_id), 'tasks', opt_fields='name,completed')
        elif workspace_id is not None:
            tasks = self.__make_req('workspaces', str(workspace_id), 'tasks', assignee='me', opt_fields='name,completed')
        else:
            raise ValueError('must pass one of project_id, workspace_id')
        tasks.sort(key=operator.itemgetter('completed'), reverse=True)
        return tasks
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

    def run(self):
        self.path[0] = self.api.workspaces()
        self.display()
        try:
            while True:
                if self.prompt():
                    self.display()
        except EOFError:
            print

    def display(self):
        pwd_len = len(self.pwd)
        if pwd_len == self.WORKSPACES:
            for w in self.path[self.WORKSPACES]:
                print w['name']
        elif pwd_len == self.PROJECTS:
            print 'me'
            for p in self.path[self.PROJECTS]:
                print p['name']
        elif pwd_len == self.TASKS:
            for t in self.path[self.TASKS]:
                if t['completed']:
                    print '\t' + colors.green(t['name'])
                elif t['name'].endswith(':'):
                    print colors.yellow(t['name'])
                else:
                    print '\t' + t['name']
        elif pwd_len == self.TASK:
            task = self.path[self.TASK]
            print task['name']
            if task['completed']:
                print colors.green('completed')
            if task['assignee']:
                print colors.yellow('assignee:'), task['assignee']['name']
            else:
                print colors.yellow('assignee:'), task['assignee']
            print colors.yellow('notes:'), task['notes']
            print colors.yellow('due on:'), task['due_on']
            print colors.yellow('comments:')
            for s in task['stories']:
                if s['type'] == 'system':
                    line = '{} {} {}'.format(s['created_by']['name'], s['text'], s['created_at'])
                    print colors.magenta(line)
                elif s['type'] == 'comment':
                    print colors.blue('{} {}'.format(s['created_by']['name'], s['created_at']))
                    print '\t' + s['text']
                else:
                    raise RuntimeError('unhandled story type: ' + s['type'])
            print colors.yellow('followers:')
            for f in task['followers']:
                print '\t' + f['name']
        else:
            raise RuntimeError('unhandled working directory depth')

    def prompt(self):
        pwd_len = len(self.pwd)
        prompt = ', '.join(map(str, self.pwd)) + '> '
        line = raw_input(colors.cyan(prompt))
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
                        self.pwd.append(w['id'])
                        projects = self.api.projects(w['id'])
                        self.path[self.PROJECTS] = projects
                        break
                else:
                    print 'could not find that workspace'
            elif pwd_len == self.PROJECTS:
                if split[1] == 'me':
                    self.pwd.append('me')
                    tasks = self.api.tasks(workspace_id=self.pwd[0])
                    self.path[self.TASKS] = tasks
                else:
                    for p in self.path[self.PROJECTS]:
                        if p['name'] == split[1]:
                            self.pwd.append(p['id'])
                            tasks = self.api.tasks(project_id=p['id'])
                            self.path[self.TASKS] = tasks
                            break
            elif pwd_len == self.TASKS:
                for t in self.path[self.TASKS]:
                    if t['name'] == split[1]:
                        self.pwd.append(t['id'])
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
    Shell(api_key).run()
