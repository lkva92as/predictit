import os
import time
from slackclient import SlackClient
import json
import requests
from datetime import datetime

f = json.load(open('secrets.json', 'r'))
BOT_ID = f['BOT_ID']
SLACK_BOT_TOKEN = f['SLACK_BOT_TOKEN']
ALERT_CHANNEL = f['ALERT_CHANNEL']
TEST_CHANNEL = f['TEST_CHANNEL']

AT_BOT = "<@" + BOT_ID + ">"
slack_client = SlackClient(SLACK_BOT_TOKEN)

def check_ticker(ticker):
    data = requests.get("https://www.predictit.org/api/marketdata/ticker/" + ticker)
    return data.text != 'null'

# get_all_matching('pres.gha')
def get_all_matching(ticker):
    data = requests.get("https://www.predictit.org/api/marketdata/all")
    response = ""
    for market in data.json()['Markets']:
        if market['TickerSymbol'].lower().startswith(ticker.lower()):
            if len(market['Contracts']) == 1:
              response += '%s: Bid: %s Ask: %s Last: %s\n' % (
                market['TickerSymbol'],
                market['Contracts'][0]['BestSellYesCost'],
                market['Contracts'][0]['BestBuyYesCost'],
                market['Contracts'][0]['LastTradePrice'],
              )
            else:
                for contract in market['Contracts']:
                    response += '- %s: Bid: %s Ask: %s Last: %s\n' % (
                      contract['TickerSymbol'],
                      contract['BestSellYesCost'],
                      contract['BestBuyYesCost'],
                      contract['LastTradePrice'],
                    )
    if response.strip() == "":
        response = "No matching contracts found"
    return response.strip()

def get_quote(ticker):
    data = requests.get("https://www.predictit.org/api/marketdata/ticker/" + ticker)
    return '%s: Bid: %s Ask: %s Last: %s' % (
      ticker,
      data.json()['Contracts'][0]['BestSellYesCost'],
      data.json()['Contracts'][0]['BestBuyYesCost'],
      data.json()['Contracts'][0]['LastTradePrice'],
    )

def handle_command(command, channel):
    """
        Receives commands directed at the bot and determines if they
        are valid commands. If so, then acts on the commands. If not,
        returns back what it needs for clarification.
    """
    if len(command) < 3:
        response = "Too short"
    elif '<' in command:
        response = 'Parsed as a url; try again'
    # elif check_ticker(command):
    #     response = get_quote(command)
    else:
        response = get_all_matching(command)
    
    slack_client.api_call("chat.postMessage", channel=channel, text=response, as_user=True)

def parse_slack_output(slack_rtm_output):
    """
        The Slack Real Time Messaging API is an events firehose.
        this parsing function returns None unless a message is
        directed at the Bot, based on its ID.
    """
    output_list = slack_rtm_output
    if output_list and len(output_list) > 0:
        for output in output_list:
            if output and 'text' in output and AT_BOT in output['text']:
                # return text after the @ mention, whitespace removed
                return output['text'].split(AT_BOT)[1].strip(), output['channel']
    return None, None

def check_for_new_contracts():
    data = requests.get("https://www.predictit.org/api/marketdata/all").json()['Markets']
    current_contracts = [x['TickerSymbol'] for x in data]

    f = open('contracts', 'r')
    old_contracts = f.read().strip().split('|')
    f.close()

    new_contracts = set(current_contracts) - set(old_contracts)

    if len(new_contracts) > 0:
        # new_contract_alert(list(new_contracts))
        new_contract_alert([x for x in data if x['TickerSymbol'] in list(new_contracts)])

        f = open('new_contracts', 'a')
        f.write('|'.join(list(new_contracts)) + ' ' + str(time.time()) + '\n')
        f.close()

        f = open('contracts', 'w')
        f.write('|'.join(set(old_contracts) | set(current_contracts)))
        f.close()

def new_contract_alert(lst):
    for contract in lst:
        msg = "New contract: " + contract['TickerSymbol'] + ' ' + contract['URL']
        slack_client.api_call("chat.postMessage", channel=ALERT_CHANNEL, text=msg, as_user=True)

if __name__ == "__main__":
    READ_WEBSOCKET_DELAY = 1 # 1 second delay between reading from firehose
    if slack_client.rtm_connect():
        print("StarterBot connected and running!")
        while True:
            command, channel = parse_slack_output(slack_client.rtm_read())
            if command and channel:
                handle_command(command, channel)
            if datetime.now().minute % 15 == 0 and datetime.now().second == 0:
                check_for_new_contracts()
            time.sleep(READ_WEBSOCKET_DELAY)
    else:
        print("Connection failed. Invalid Slack token or bot ID?")
