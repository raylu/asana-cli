#!/usr/bin/env python
# vim: set sw=4 ts=4:

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
    def tasks(self, workspace_id):
        return self.__make_req('workspaces', str(workspace_id), 'tasks', assignee='me')
    def task(self, task_id):
        task = self.__make_req('tasks', str(task_id))
        stories = self.__make_req('tasks', str(task_id), 'stories')
        task['stories'] = stories
        return task

class Shell(object):
    def __init__(self, api_key):
        self.api = API(api_key)
        self.workspaces = None
        self.tasks = None
        self.pwd = []

        readline.set_completer(self.complete)
        readline.set_completer_delims('')
        readline.parse_and_bind('tab: complete')

    def run(self):
        self.display()
        try:
            while True:
                if self.prompt():
                    self.display()
        except EOFError:
            print

    def display(self):
        pwd_len = len(self.pwd)
        if pwd_len == 0:
            self.workspaces = self.api.workspaces()
            for w in self.workspaces:
                print w['name']
        elif pwd_len == 1:
            self.tasks = self.api.tasks(self.pwd[0])
            for t in self.tasks:
                print t['name']
        elif pwd_len == 2:
            self.task = self.api.task(self.pwd[1])
            print self.task['name']
            if self.task['completed']:
                print 'completed'
            print 'assignee', self.task['assignee']
            print 'notes:', self.task['notes']
            print 'due on:', self.task['due_on']
            print 'comments:'
            for s in self.task['stories']:
                print s['created_by']['name'], s['created_at']
                print '\t' + s['text']
            print 'followers:'
            for f in self.task['followers']:
                print '\t' + f['name']
        else:
            raise RuntimeError('unhandled working directory depth')

    def prompt(self):
        pwd_len = len(self.pwd)
        line = raw_input(', '.join(map(str, self.pwd)) + '> ')
        split = line.split(' ', 1)
        command = split[0]
        if command == 'cl':
            if pwd_len == 0:
                for w in self.workspaces:
                    if w['name'] == split[1]:
                        self.pwd.append(w['id'])
                        break
                else:
                    print 'could not find that workspace'
            elif pwd_len == 1:
                for t in self.tasks:
                    if t['name'] == split[1]:
                        self.pwd.append(t['id'])
                        break
                else:
                    print 'could not find that task'
            elif pwd_len == 2:
                pass
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
        pwd_len = len(self.pwd)
        if pwd_len == 0:
            for w in self.workspaces:
                if ltext in w['name'].lower():
                    if match == state:
                        return 'cl ' + w['name']
                    match += 1
        elif pwd_len == 1:
            for t in self.tasks:
                if ltext in t['name'].lower():
                    if match == state:
                        return 'cl ' + t['name']
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
