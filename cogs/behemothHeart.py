from asyncio.windows_events import NULL
from os.path import exists
import discord
from discord.ext import commands
import asyncio
import cogs.server_controller as server_controller
#import cogs.db_broker as db_broker
from datetime import datetime
import traceback
import os
import time
import threading
from threading import Thread

#hard_reset = False

discver = (discord.__version__).split(".")
intents = discord.Intents.default()
if int(discver[0]) >= 2: intents.message_content=True
bot = commands.Bot(command_prefix='!',case_insensitive=True,intents=intents)

alive = False
alive_bkp = False
global dm_active_embed

class heartbeat(commands.Cog):
    def __init__(self,server):
        self.server = server
    def set_server_config(self,data):
        self.server_data = data
    def health_check(self):
        return
    def get_poll_interval(self):
        return self.timer
    def get_player_count(self):
        return server_controller.honCMD().get_player_count(self.server_data['_pid'])
    async def start_heart(self):
        self.timer = 0
        while True:
            self.timer += 1
            #print(self.server.id)
            await asyncio.sleep(1)

class heartbeat2(commands.Cog):
    def __init__(self, bot):
        # self.bot = bot
        # self.alive = False
        # self.processed_data_dict = svr_state.getDataDict()
        return
    def time():
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    @bot.command()
    async def heart(self,ctx):
        await ctx.send("💓")
    @bot.command()
    async def getembedlog(self,ctx,log_embed):
        global dm_active_embed
        try:
            dm_active_embed = log_embed
        except Exception: 
            print(traceback.format_exc())
            print("most likely because the auto-sync function is being used, therefore we can't send a log message to anyone yet.")

    def print_and_log(app_log,log_msg,log_lvl):
        print(log_msg)
        svr_state.append_line_to_file(f"{app_log}",log_msg,log_lvl)
    
    def health_checks(self,type):
        print(type)

    #@bot.command()
    def startheart(self,server,config,ctx):
        global dm_active_embed
        global alive
        print(server)
        #   prepare the heartbeat
        alive = True
        #   check the most recent match id
        svr_state.check_current_match_id(False,False,server,config)
        #   list of default (allowed) maps
        # available_maps_bkp = svr_state.getData("availMaps")
        
        self.server_status = svr_state.getStatus()
        self.match_status = svr_state.getMatchInfo()

        #   
        self.server_status.update({'hard_reset':False})
        # self.server_status.update({'server_ready':False})

        
        # determine status of discord bot
        #   TODO: healthcheck for bot running?
        if ctx != None:
            bot_message = self.bot.get_cog("embedManager")
            self.server_status.update({'bots_running':True})
            # server.update({'bots_running':True})
        elif ctx == None:
            self.server_status.update({'bots_running':False})
            #server.update({'bots_running':False})
        
        #svr_state.append_line_to_file(f"{ self.processed_data_dict['app_log']}",f"Initialising variables (soft). Data Dump: {dmgr.mData().return_simple_dict( self.processed_data_dict)}","INFO")
        async def send_user_msg(ctx,log_msg,alert):
            send_new_message = False
            msg_sent = False
            global dm_active_embed

            log_msg = log_msg.replace("\n","BRK")
            
            if ctx == False:
                send_new_message = True
            if alert and ctx:
                if "crash" in log_msg and self.processed_data_dict['disc_alert_on_crash'] == 'False':
                    send_new_message = False
                elif "lag spike" in log_msg and self.processed_data_dict['disc_alert_on_lag'] == 'False':
                    send_new_message = False
                else: send_new_message = True
            
            if not send_new_message:
                user_embed = await bot_message.embedLog(f"[{heartbeat.time()}] {log_msg}",alert,self.processed_data_dict)
                try:
                    edit_result = await dm_active_embed[0].edit(embed=user_embed)
                    print("Updated server companion message with owner.")
                    msg_sent = True
                except (discord.errors.NotFound,discord.errors.Forbidden,discord.errors.HTTPException,UnboundLocalError):
                    print(traceback.format_exc())
                    svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
                    if discord.errors.HTTPException:
                        heartbeat.print_and_log(f"{self.processed_data_dict['app_log']}",f"Most likely we are being rate limited\nResponse from last discord API request: {edit_result}","WARNING")
                    elif UnboundLocalError:
                        heartbeat.print_and_log(f"{self.processed_data_dict['app_log']}","previous message may have been deleted. Making a new one","INFO")
                        send_new_message=True
            if send_new_message:
                try:
                    user_embed = await bot_message.embedLog(f"[{heartbeat.time()}] {log_msg}",alert,self.processed_data_dict)
                    if ctx != False: await dm_active_embed[0].delete()
                    dm_active_embed[0] = await ctx.send(embed=user_embed)
                    print("Sent new server companion message to owner.")
                    msg_sent = True
                    embedFile = open(self.processed_data_dict['dm_discord_temp'], 'w')
                    embedFile.write(str(dm_active_embed[0].channel.id)+","+str(dm_active_embed[0].id)+"\n")
                    embedFile.close()
                except (discord.errors.HTTPException,Exception):
                    print(traceback.format_exc())
                    svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
                    if discord.errors.HTTPException: print(f"Most likely we are being rate limited\nResponse from last discord API request: {dm_active_embed[0]}")
            if not msg_sent:
                heartbeat.print_and_log(f"{self.processed_data_dict['app_log']}","Skipping this message update, will try again later.","INFO")
                if alert:
                    alert_list = open(self.processed_data_dict['dm_discord_hist']).readlines()
                    alert_list.append(log_msg)
                    with open(self.processed_data_dict['dm_discord_hist'], 'w') as f:
                        for line in alert_list:
                            line = line.replace("\n","")
                            f.write(f"{line}\n")
                else:
                    event_list = open(self.processed_data_dict['dm_discord_hist']).readlines()
                    event_list.append(log_msg)
                    with open(self.processed_data_dict['dm_discord_hist'], 'w') as f:
                        for line in event_list:
                            line = line.replace("\n","")
                            f.write(f"{line}\n")
                
        #   in-memory counters, thresholds and other variables
        local = threading.local()
        local.waiting = False
        local.proxy_online = False
        local.heartbeat_freq = 1
        local.process_priority = "REALTIME"
        local.process_priority = local.process_priority.upper()
        local.counter_gamecheck = 0
        local.counter_health_checks = 0
        local.counter_ipcheck = 0
        local.counter_game_end = 0
        local.counter_check_lag = 0
        local.counter_pending_players_leaving = 0
        local.counter_keeper=0

        local.healthcheck_first_run = True
        local.announce_proxy_health = True

        while alive:
            time.sleep(1)
            try: server['players_connected']= svr_state.playerCount(server,config)
            except Exception as e: print(e)
            #db_handler.Server().upsert_by_id(server,server.doc_id)

            #print(f"Server: {server.doc_id}")
        # heartbeat.print_and_log(f"{self.processed_data_dict['app_log']}",f"Initialising variables. Data Dump: {self.processed_data_dict}","INFO")
        # while alive:
#             try:
#                 proc_priority = svrcmd.honCMD.get_process_priority(self.processed_data_dict['hon_file_name'])
#             except Exception: pass

#             await asyncio.sleep(config[0]['application_data']['timers']['heartbeat'])

#             try:
#                 if self.server_status['hon_pid'] == 'pending':
#                     playercount = svr_state.playerCount()
#                 else:
#                     playercount = svr_state.playerCount_pid()
#                 counter_keeper+=1
#                 # check the live DDOS blacklist for any changes requiring action in firewall
#                 if (counter_keeper >= threshold_keeper or self.server_status['bot_first_run'] == True) and self.processed_data_dict['svr_id'] == "1":
#                     counter_keeper=0
#                     self.server_status.update({'bot_first_run':False})
#                     svrcmd.honCMD.launch_keeper()
#                 # check for a scheduled restart, and queue it
#                 if self.server_status['hard_reset'] == False:
#                     try:
#                         self.server_status.update({'hard_reset':svr_state.check_for_updates("pending_restart")})
#                     except Exception:
#                         print(traceback.format_exc())
#                         svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
#                 # check for or a scheduled shutdown, and queue it
#                 if self.server_status['scheduled_shutdown']==False:
#                     try:
#                         self.server_status.update({'scheduled_shutdown':svr_state.check_for_updates("pending_shutdown")})
#                     except Exception:
#                         print(traceback.format_exc())
#                         svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
#             except Exception:
#                 print(traceback.format_exc())
#                 svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
            
#             if playercount >=2:
#                 if proc_priority != process_priority:
#                     try:
#                         svr_state.changePriority(True)
#                     except Exception:
#                         print(traceback.format_exc())
#                         svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
#             try:
#                 if playercount == -3:
#                     if 'crash' in self.server_status:
#                         if self.server_status['crash'] == True:
#                             if self.server_status['server_start_attempts'] <= 3:
#                                 self.server_status.update({'server_start_attempts':self.server_status['server_start_attempts']+1})
#                                 # server may have crashed, check if we can restart.
#                                 try:
#                                     if svr_state.startSERVER("Attempting to start crashed instance"):
#                                         heartbeat.print_and_log(f"{self.processed_data_dict['app_log']}",f"SERVER Auto-Recovered due to most likely crash. ``{self.processed_data_dict['hon_game_dir']}`` for any crash dump files.","WARNING")
#                                         if self.match_status['now'] == 'idle':
#                                             if ctx != None: await send_user_msg(ctx,f"[WARN] SERVER Auto-Recovered due to most likely crash. {self.processed_data_dict['hon_game_dir']} may contain a crash DUMP.\nNo games were in progress.",True)
#                                         else:
#                                             if ctx != None: await send_user_msg(ctx,f"""[WARN] SERVER Auto-Recovered due to most likely crash. {self.processed_data_dict['hon_game_dir']} may contain a crash DUMP.
# Game state: {self.match_status['now']}
# Match ID: {self.match_status['match_id'].replace('M','')}
# Match Time: {self.match_status['match_time']}
# Players connected: {playercount}
# Process Priority: {svrcmd.honCMD.get_process_priority(self.processed_data_dict['hon_file_name'])}
# Assigned CPU Core: {svrcmd.honCMD.get_process_affinity(self.server_status['hon_pid_hook'])}""",True)
#                                         continue
#                                 except Exception:
#                                     print(traceback.format_exc())
#                                     svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
#                             else:
#                                 print("exceeded max crash recovery attempts")
#                                 if ctx != None: await send_user_msg(ctx,f"Reached maximum # of attempts to restart crashed hon instance. Manual restart required.",True)
#                     if not proxy_online:
#                         if svrcmd.honCMD.check_port(int(self.processed_data_dict['svr_proxyPort'])):
#                             announce_proxy_health = True
#                             proxy_online = True
#                             svr_state.startSERVER("Proxy was offline. Now it's online, attempting to start dead instance")
#                         else:
#                             if announce_proxy_health:
#                                 announce_proxy_health = False
#                                 print("proxy is not online. Waiting.")
#             except Exception:
#                 print(traceback.format_exc())
#                 svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")

#             try:
#                 if playercount == 0:
#                     if 'replays_cleaned_once' not in self.server_status and self.match_status['now'] == 'idle':
#                         #
#                         # move replays off into the manager directory. clean up other temporary files
#                         print("moving replays for first launch of adminbot.")
#                         svr_state.move_replays_and_stats("Called for first launch of adminbot, with 0 players connected")
#                         svr_state.clean_old_logs()
#                     if self.server_status['tempcount'] > 0:
#                         svr_state.check_current_match_id(False,True)
#                         # if self.match_status['now'] in ['in game','in lobby']:
#                         #     svr_state.initialise_variables("reload")
#                     #   Check the process priority, set it to IDLE if it isn't already
#                     if proc_priority != "IDLE" and self.match_status['now'] == 'idle':
#                         try:
#                             svr_state.changePriority(False)
#                         except Exception:
#                             svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
#                     """   [Players: 0] scheduled (restart / shutdown) checks """
#                     #   action a scheduled restart, if it's been queued
#                     if self.server_status['hard_reset'] == True:
#                         if self.match_status['now'] in ["in lobby","in game"]:
#                             if svr_state.wait_for_replay(replay_threshold):
#                                 svr_state.restartSELF("Scheduled restart initiated.")
#                         else:
#                             svr_state.restartSELF("Scheduled restart initiated.")
#                     #   action a scheduled shutdown, if it's been queued
#                     if self.server_status['scheduled_shutdown'] == True:
#                         if self.match_status['now'] in ["in lobby","in game"]:
#                             if svr_state.wait_for_replay(replay_threshold):
#                                 svr_state.stopSELF("Scheduled shutdown initiated.")
#                             else: pass
#                         else:
#                             print("scheduled shutdown, moving to stop server")
#                             svr_state.stopSELF("Scheduled shutdown initiated.")
#                     #   check for or action a natural restart inbetween games
#                     if self.match_status['now'] in ["in lobby","in game"]:
#                         if self.match_status['now'] == "in game":
#                             print("Server in game, waiting for replay..")
#                             svr_state.wait_for_replay(replay_threshold)
#                         else:
#                             print("In lobby phase, re-initialising variables")
#                             svr_state.initialise_variables("soft","soft - called by players returning to 0, and being 'in lobby'")
                    
#                     """  [Players: 0] idle game health checks """
#                     counter_ipcheck +=1
#                     if self.match_status['now'] == "idle":
#                         #   compare the hon process commandline arguments, to the expected commandline arguments from config file
#                         running_cmdline = self.server_status['hon_pid_hook'].cmdline()
#                         incoming_cmd = dmgr.mData().return_commandline(self.processed_data_dict)
#                         if running_cmdline != incoming_cmd:
#                             log_msg = "A configuration change has been detected. The server is being restarted to load the new configuration."
#                             svr_state.restartSERVER(False,log_msg)
#                             if ctx != None: logEmbed = await send_user_msg(ctx,log_msg,False)
#                         #   check whether the code should "summon" the hon server instance, because it's running under a different user context
#                         if self.processed_data_dict['use_console'] == 'True':
#                             current_login = os.getlogin()
#                             if "SYSTEM" in self.server_status['hon_pid_owner']:
#                             # if current_login not in self.server_status['hon_pid_owner']:
#                                 log_msg = f"The user account which started the server is not the same one which just configured the server. Restarting to load server on {current_login} login"
#                                 svr_state.restartSERVER(False,log_msg)
#                                 if ctx != None: logEmbed = await send_user_msg(ctx,log_msg,False)
#                         else:
#                             if "SYSTEM" not in self.server_status['hon_pid_owner'].upper():
#                                 log_msg = "Restarting the server as it has been configured to run in windows service mode. Console will be offloaded to back end system."
#                                 svr_state.restartSERVER(False,log_msg)
#                                 if ctx != None: logEmbed = await send_user_msg(ctx,log_msg,False)
#                         #   every counter_ipcheck_threshold seconds, check if the public IP has changed for the server. Schedule a restart if it has
#                         if counter_ipcheck == counter_ipcheck_threshold and 'static_ip' not in self.processed_data_dict:
#                             counter_ipcheck = 0
#                             check_ip = dmgr.mData.getData(NULL,"svr_ip")
#                             if check_ip != self.processed_data_dict['svr_ip']:
#                                 #TODO: Check if this causes any restart loop due to svr_ip not updating?
#                                 svr_state.restartSERVER(False,f"The server's public IP has changed from {self.processed_data_dict['svr_ip']} to {check_ip}. Restarting server to update.")
#                                 if ctx != None: await send_user_msg(ctx,f"The server's public IP has changed from {self.processed_data_dict['svr_ip']} to {check_ip}. Restarting server to update.",False)
#                 # every x seconds, check if the proxy port is still listening.
#                 counter_health_checks +=1
#                 if counter_health_checks>=threshold_health_checks or healthcheck_first_run:
#                     healthcheck_first_run = False
#                     counter_health_checks=0
#                     if self.processed_data_dict['use_proxy'] == 'True':
#                         if 'svr_proxyPort' in self.processed_data_dict:
#                             proxy_online=svrcmd.honCMD.check_port(int(self.processed_data_dict['svr_proxyPort']))
#                             if proxy_online != self.server_status['proxy_online']:
#                                 self.server_status.update({'proxy_online':proxy_online})
#                                 if proxy_online:
#                                     print(f"Health check: server proxy port {self.processed_data_dict['svr_proxyPort']} healthy")
#                                 else:
#                                     heartbeat.print_and_log(f"{self.processed_data_dict['app_log']}","The proxy port has stopped listening.","WARNING")
#                                     if self.match_status['now'] == 'in game':
#                                         log_msg = f"[ERR] The proxy port ({self.processed_data_dict['svr_proxyPort']}) has stopped listening.\n{self.match_status['match_id']} was ongoing and might be affected."
#                                     else:
#                                         log_msg = f"[ERR] The proxy port ({self.processed_data_dict['svr_proxyPort']}) has stopped listening."
#                                     print(log_msg)
#                                     if ctx != None: logEmbed = await send_user_msg(ctx,log_msg,False)
#                             auto_pinger_online = svrcmd.honCMD.check_port(int(self.processed_data_dict['svr_proxyPort']-int(self.processed_data_dict['svr_id'])))
#                     else:
#                         auto_pinger_online = svrcmd.honCMD.check_port(int(self.processed_data_dict['svr_port']-int(self.processed_data_dict['svr_id'])))
#                     if 'auto_pinger_online' not in self.server_status or (auto_pinger_online != self.server_status['auto_pinger_online']):
#                         self.server_status.update({'auto_pinger_online':auto_pinger_online})
#                         if not auto_pinger_online:
#                             svrcmd.honCMD.start_autoping_responder()
#             except Exception:
#                 print(traceback.format_exc())
#                 svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
#             try:
#                 #   Check whether the server has finished launching, by querying the voice listening port (open or not?)
#                 if self.server_status['server_ready'] == False:
#                     if svrcmd.honCMD.check_port(int(self.processed_data_dict['svr_proxyLocalVoicePort'])):
#                         waiting = False
#                         print(f"Health check: local voice port {self.processed_data_dict['svr_proxyLocalVoicePort']} healthy")
#                         print(f"Server ready")
#                         self.server_status.update({'server_ready':True})
#                     else:
#                         if not waiting:
#                             waiting = True
#                             print(f"Port {self.processed_data_dict['svr_proxyLocalVoicePort']} is not open. Waiting for server to start")
#             except Exception:
#                 print(traceback.format_exc())
#                 svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
#             try:
#                 if playercount >= 1:
#                     if self.match_status['now'] == "in lobby":
#                         #   every threshold_gamecheck seconds, check whether the match has begun
#                         counter_gamecheck+=1
#                         if counter_gamecheck==threshold_gamecheck:
#                             counter_gamecheck=0
#                             try:
#                                 if svr_state.check_game_started():
#                                     if ctx != None: await send_user_msg(ctx,f"[OK] [{self.match_status['match_id']}] match started.",False)
#                             except Exception:
#                                 print(traceback.format_exc())
#                                 svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
#                     elif self.match_status['now'] == "in game":
#                         #   get the current in-game match time elapsed
#                         svr_state.check_current_game_time()
#                         counter_check_lag += 1
#                         if counter_check_lag >= threshold_check_lag:
#                             counter_check_lag = 0
#                             try:
#                                 time_lagged = svrcmd.honCMD.count_skipped_frames(self)
#                                 if time_lagged > 5:                            
#                                     self.processed_data_dict.update({'match_id':self.match_status['match_id']})
#                                     if ctx != None: await send_user_msg(ctx,f"""[ERR] {time_lagged} second lag spike over the last {threshold_check_lag_mins} minutes.
# Match ID: {self.match_status['match_id'].replace('M','')}
# Match Time: {self.match_status['match_time']}
# Players connected: {playercount}
# Process Priority: {svrcmd.honCMD.get_process_priority(self.processed_data_dict['hon_file_name'])}
# Assigned CPU Core: {svrcmd.honCMD.get_process_affinity(self.server_status['hon_pid_hook'])}""",True)
#                                     #   Please check https://hon-elk.honfigurator.app:5601/app/dashboards#/view/c9a8c110-4ca8-11ed-b6c1-a9b732baa262/?_a=(filters:!((query:(match_phrase:(Server.Name:{hoster}))),(query:(match_phrase:(Match.ID:{self.match_status['match_id'].replace('M','')})))))
#                             except Exception:
#                                 print(traceback.format_exc())
#                                 svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
#                     else:
#                         if playercount > 1:
#                             #   player has connected, check the match ID.
#                             #   This works because there was no match ID, now there is. This won't trigger if the console is restarted while a player is connected.
#                             svr_state.check_current_match_id(True,False)
#                             self.server_status.update({'at_least_2_players':True})
#                         else:
#                             #   check the match ID if 2 or more players are connected and the console has been restarted.
#                             #   It has no other way to tell if it's an old match ID or a new one
#                             svr_state.check_current_match_id(False,False)
#                     if self.match_status['now'] != "idle":
#                         if not self.match_status['match_info_obtained']:
#                             #   poll the match logs until the lobby/match information is obtained
#                             try:
#                                 svr_state.get_match_information()
#                             except Exception:
#                                 print(traceback.format_exc())
#                                 svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
#                     if (self.server_status['game_map'] != "empty" and self.server_status['game_map'] not in available_maps_bkp):
#                         svr_state.restartSERVER(True,f"Server restarting due to attempt to crash server with false map.")

#                     elif (self.server_status['game_mode'] == "botmatch" or self.server_status['game_mode'] == "BotMatch") and self.processed_data_dict['allow_botmatches'] == 'False':
#                         svr_state.restartSERVER(True,f"Server restarting due to bot match (disallowed).")
#                     #
#                     #   cookie health checks
#                     if self.server_status['game_log_location'] != 'empty':
#                         cookie=svrcmd.honCMD.check_cookie(self.processed_data_dict,self.server_status['game_log_location'],'slave_cookie_check')
#                         if cookie != self.server_status['cookie']:
#                             self.server_status.update({'cookie':cookie})
#                             #self.server_status.update({'tempcount':-5})
#                             if cookie == False:
#                                 heartbeat.print_and_log(f"{self.processed_data_dict['app_log']}",f"No session cookie.","WARNING")
#                                 if ctx != None: logEmbed = await send_user_msg(ctx,f"[ERR] Session cookie lost.",True)
#                             else:
#                                 heartbeat.print_and_log(f"{self.processed_data_dict['app_log']}",f"Connection restored.","INFO")
#                                 if ctx != None: await send_user_msg(ctx,f"[OK] Connection restored.",False)
#             except Exception:
#                 print(traceback.format_exc())
#                 svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
#             try:
#                 if playercount == 1:
#                     if self.match_status['now'] == "in game":
#                         #   OPTION 1: every threshold_game_end_check seconds, check if the match is over, despite there still being 1 player connected.
#                         counter_game_end +=1
#                         print(f"{counter_game_end}/{threshold_game_end_check} remaining until server force close")
#                         if counter_game_end >= threshold_game_end_check:
#                             counter_game_end = 0
#                             if svr_state.check_game_ended():
#                                 svr_state.restartSERVER(True,f"[{self.match_status['match_id'] if 'match_id' in self.match_status else 'No Match ID'}] Server restarting due to game end but 1 player has remained connected for {threshold_game_end_check} seconds.")
#                                 svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"[{self.match_status['match_id'] if 'match_id' in self.match_status else 'No Match ID'}] Server restarting due to game end but 1 player has remained connected for {threshold_game_end_check} seconds.","WARNING")
#                                 if ctx != None: await send_user_msg(ctx,f"[WARN] [{self.match_status['match_id']}] Server restarting due to game end but 1 player has remained connected for {threshold_game_end_check} seconds.",True)
#                         #   OPTION 2: if the match time is over 1 hour, and 1 player is connected, start a timer for 2 minutes, after that, restart server
#                         if self.server_status['at_least_2_players']:
#                             match_time = self.match_status['match_time']
#                             if ":" in match_time:
#                                 match_too_long = match_time.split(":")
#                                 match_too_long_hrs = int(match_too_long[0])
#                                 match_too_long_mins = int(match_too_long[1])
#                                 if match_too_long_mins >= 45 or (match_too_long_hrs >= 1):
#                                     counter_pending_players_leaving +=1
#                                     if counter_pending_players_leaving >= threshold_pending_players_leaving:
#                                         counter_pending_players_leaving = 0
#                                         msg = f"Server restarting due to match ongoing for 45+ mins with only 1 players connected. All other players have left the game."
#                                         svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"[{self.match_status['match_id']}] Server restarting due to match ongoing for 45+ mins with only 1 players connected. All other players have left the game.","WARNING")
#                                         if ctx != None: await send_user_msg(ctx,f"[WARN] [{self.match_status['match_id']}] Server restarting due to match ongoing for 45+ mins with only 1 players connected. All other players have left the game.",True)
#                                         print(msg)
#                                         svr_state.restartSERVER(True,msg)
#             except Exception:
#                 print(traceback.format_exc())
#                 svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
            
#             if 'tempcount' not in self.server_status or playercount != self.server_status["tempcount"]:
#                 #   print the playercount when the playercount changes
#                 self.server_status.update({'tempcount':playercount})        
#                 data = {'players_connected':int(playercount),'name':self.processed_data_dict['svr_identifier']}
#                 db_manager.Update.update_db(data)
#                 print(f"players: {playercount}")
    @bot.command()
    async def priority(self,ctx):
        global dm_active_embed
        bot_message = self.bot.get_cog("embedManager")
        time.sleep(int(self.processed_data_dict['svr_id'])*2)
        try:
            user_embed = await bot_message.embedLog(f"[{heartbeat.time()}] Summoned.",False,self.processed_data_dict)
            await dm_active_embed[0].delete()
            dm_active_embed[0] = await ctx.send(embed=user_embed)
            embedFile = open(self.processed_data_dict['dm_discord_temp'], 'w')
            embedFile.write(str(dm_active_embed[0].channel.id)+","+str(dm_active_embed[0].id)+"\n")
            embedFile.close()
        except Exception:
            print(traceback.format_exc())
            svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
    @bot.command()
    async def stopheart(self,ctx):
        global alive
        alive = False
    @bot.command()
    async def statusheart(self,ctx):
        return alive
    @bot.command()
    async def giveCPR(self,ctx,hoster):
        if hoster == self.processed_data_dict['svr_hoster'] or hoster == self.processed_data_dict['svr_identifier']:
            try:
                await ctx.message.delete()
            except Exception:
                print(traceback.format_exc())
                svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
            if not alive:
                await ctx.invoke(bot.get_command('startheart'),ctx)
    @bot.command()
    async def kick(self,ctx,hoster):
        if hoster == self.processed_data_dict['svr_hoster'] or hoster == self.processed_data_dict['svr_identifier']:
            try:
                await ctx.message.delete()
            except Exception:
                print(traceback.format_exc())
                svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
            if hoster == self.processed_data_dict['svr_hoster']:
                await asyncio.sleep(int(self.processed_data_dict['svr_id']))
            self.server_status.update({'update_embeds':True})
            self.server_status.update({'tempcount':-5})
    @bot.command()
    async def pullPlug(self,ctx,hoster):
        if hoster == self.processed_data_dict['svr_identifier']:
            try:
                await ctx.message.delete()
            except Exception:
                print(traceback.format_exc())
                svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
            await ctx.invoke(bot.get_command('stopheart'),ctx)
    @bot.command()
    async def heartbeat(self,ctx,hoster):
        if hoster == self.processed_data_dict['svr_hoster'] or hoster == self.processed_data_dict['svr_identifier']:
            try:
                await ctx.message.delete()
            except Exception: pass
            playercount = svrcmd.honCMD().playerCount()
            if hoster == self.processed_data_dict['svr_hoster']:
                await asyncio.sleep(int(self.processed_data_dict['svr_id']))
            alive = await ctx.invoke(bot.get_command('statusheart'),ctx)
            try:
                if alive:
                    await ctx.send(f"{self.processed_data_dict['svr_identifier']} Behemoth heart beating 💓 {playercount} players connected",delete_after=5)
                else:
                    await ctx.send(f"{self.processed_data_dict['svr_identifier']} Behemoth heart stopped! :broken_heart:",delete_after=5)
            except Exception:
                print(traceback.format_exc())
                svr_state.append_line_to_file(f"{self.processed_data_dict['app_log']}",f"{traceback.format_exc()}","WARNING")
    
async def setup(bot):
    if int(discver[0]) >=2:
        await bot.add_cog(heartbeat(bot))
    else:
        bot.add_cog(heartbeat(bot))