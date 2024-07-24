#!/usr/bin/python3
# The purpose of lp-to-jira is to take a launchad bug ID and create a new Entry in JIRA in a given project


import os
import json


class jira_api:
    def __init__(self, credstore="{}/.jira.token".format(os.path.expanduser("~"))):
        snap_home = os.getenv("SNAP_USER_COMMON")
        if snap_home:
            self.credstore = f"{snap_home}/.jira.token"
        else:
            self.credstore = credstore
        try:
            with open(self.credstore) as f:
                config = json.load(f)
                self.server = config["jira-server"]
                self.login = config["jira-login"]
                self.token = config["jira-token"]
        except (FileNotFoundError, json.JSONDecodeError):
            print(
                f"JIRA Token information file {self.credstore} could not be found or parsed."
            )
            print("")
            gather_token = input(
                "Do you want to enter your JIRA token information now? (Y/n) "
            )
            if gather_token == "n":
                raise ValueError("JIRA API isn't initialized")
            self.server = input("Please enter your jira server address : ")
            self.login = input("Please enter your email login for JIRA : ")
            self.token = input(
                "Please enter your JIRA API Token (see https://id.atlassian.com/manage-profile/security/api-tokens) : "
            )
            save_token = input(
                "Do you want to save those credentials for future use or lp-to-jira? (Y/n) "
            )
            if save_token != "n":
                try:
                    data = {}
                    data["jira-server"] = self.server
                    data["jira-login"] = self.login
                    data["jira-token"] = self.token
                    with open(self.credstore, "w+") as f:
                        json.dump(data, (f))
                except (FileNotFoundError, json.JSONDecodeError):
                    raise ValueError("JIRA API isn't initialized")
