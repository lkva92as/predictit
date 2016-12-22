#!/usr/bin/env python3
import os
import time
from slackclient import SlackClient
import json
import requests
from datetime import datetime
import redis

f = json.load(open('secrets.json', 'r'))
BOT_ID = f['BOT_ID']
SLACK_BOT_TOKEN = f['SLACK_BOT_TOKEN']
if os.environ.get('PI_ENV') == 'production':
    ALERT_CHANNEL = f['GENERAL_CHANNEL']
else:
    ALERT_CHANNEL = f['TEST_CHANNEL']

AT_BOT = "<@" + BOT_ID + ">"
slack_client = SlackClient(SLACK_BOT_TOKEN)

r = redis.Redis()

def last_updated():
    ts = r.get('pi:last-updated')
    return int(ts) if ts else 0

def save_update_ts(ts):
    r.set('pi:last-updated', ts)

def fetch_data():
    if time.time() - last_updated() > 30:
        data = requests.get("https://www.predictit.org/api/marketdata/all")
        if data.status_code != 200:
            print("PI api call failed")
            return {}
        save_update_ts(int(time.time()))
        check_for_new_contracts(json.loads(r.get('pi:data').decode('utf-8')), data.json()['Markets'])
        r.set('pi:data', json.dumps(data.json()['Markets']))
        return data.json()['Markets']
    else:
        return json.loads(r.get('pi:data').decode('utf-8'))

def check_for_new_contracts(existing_data, current_data):
    existing_markets = [x['ID'] for x in existing_data]
    for market in current_data:
        if market['ID'] not in existing_markets:
            msg = "New market: " + market['TickerSymbol'] + ' ' + market['URL']
            post_message(ALERT_CHANNEL, msg)
        elif len(market['Contracts']) > 1:
            existing_contracts = [x['ID'] for x in market['Contracts']]
            for contract in market['Contracts']:
                if contract['ID'] not in existing_contracts:
                    msg = "New contract: " + contract['TickerSymbol'] + ' in market ' + market['TickerSymbol']
                    post_message(ALERT_CHANNEL, msg)

def get_all_matching(ticker):
    data = fetch_data()
    response = ""
    for market in data:
        if market['TickerSymbol'].lower().startswith(ticker.lower()):
            if len(market['Contracts']) == 1:
              response += '%s: Bid: %s Ask: %s Last: %s\n %s\n' % (
                market['TickerSymbol'],
                market['Contracts'][0]['BestSellYesCost'],
                market['Contracts'][0]['BestBuyYesCost'],
                market['Contracts'][0]['LastTradePrice'],
                market['Contracts'][0]['URL'],
              )
            else:
                for contract in market['Contracts']:
                    if contract['BestSellYesCost'] == None:
                        continue
                    response += '- %s: Bid: %s Ask: %s Last: %s\n' % (
                      contract['TickerSymbol'],
                      contract['BestSellYesCost'],
                      contract['BestBuyYesCost'],
                      contract['LastTradePrice'],
                    )
                response += market['URL'] + '\n'
    if response.strip() == "":
        response = "No matching contracts found"
    return response.strip()

def contracts_in_range(low, high):
    data = requests.get("https://www.predictit.org/api/marketdata/all")
    response = ""
    for market in data.json()['Markets']:
        if len(market['Contracts']) == 1 and round(float(market['Contracts'][0]['LastTradePrice'])*100) in range(low,high+1):
          response += '%s %s\n' % (
            market['Contracts'][0]['LastTradePrice'],
            market['TickerSymbol'],
          )
        else:
            for contract in market['Contracts']:
                if round(float(contract['LastTradePrice'])*100) in range(low,high):
                    response += '%s %s - %s\n' % (
                        contract['LastTradePrice'],
                        market['TickerSymbol'],
                        contract['TickerSymbol'],
                    )
    return response.strip()

def handle_command(command, channel):
    if len(command) < 3:
        response = "Too short"
    elif '<' in command:
        response = 'Parsed as a url; try again'
    elif command.lower().startswith("range"):
        cmd, low, high = command.split(' ')
        response = contracts_in_range(int(low), int(high))
    else:
        response = get_all_matching(command)
    post_message(channel, response)

def post_message(channel, response):
    print(str(datetime.now()) + ' ' + response)
    slack_client.api_call("chat.postMessage", channel=channel, text=response, as_user=True)

def parse_slack_output(slack_rtm_output):
    output_list = slack_rtm_output
    if output_list and len(output_list) > 0:
        for output in output_list:
            if output and 'text' in output and AT_BOT in output['text']:
                # return text after the @ mention, whitespace removed
                return output['text'].split(AT_BOT)[1].strip(), output['channel']
    return None, None

if __name__ == "__main__":
    READ_WEBSOCKET_DELAY = 1 # 1 second delay between reading from firehose
    if slack_client.rtm_connect():
        print("StarterBot connected and running!")
        time.sleep(1)
        while slack_client.rtm_read():
            pass

        while True:
            try:
                command, channel = parse_slack_output(slack_client.rtm_read())
                if command and channel:
                    handle_command(command, channel)
                if time.time() - last_updated() > 600:
                    fetch_data()
            except:
                print(str(datetime.now()) + " Error: " + str(command))
            time.sleep(READ_WEBSOCKET_DELAY)
    else:
        print("Connection failed. Invalid Slack token or bot ID?")
