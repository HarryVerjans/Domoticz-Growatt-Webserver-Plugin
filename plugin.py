############################################################################################
# 	Growatt Inverter Python Plugin for Domoticz                                   	   #
#                                                                                          #
# 	MIT License                                                                        #
#                                                                                          #
#	Copyright (c) 2018 tixi                                                            #
#                                                                                          #
#	Permission is hereby granted, free of charge, to any person obtaining a copy       #
#	of this software and associated documentation files (the "Software"), to deal      #
#	in the Software without restriction, including without limitation the rights       #
#	to use, copy, modify, merge, publish, distribute, sublicense, and/or sell          #
#	copies of the Software, and to permit persons to whom the Software is              #
#	furnished to do so, subject to the following conditions:                           #
#                                                                                          #
#	The above copyright notice and this permission notice shall be included in all     #
#	copies or substantial portions of the Software.                                    #
#                                                                                          #
#	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR         #
#	IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,           #
#	FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE        #
#	AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER             #
#	LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,      #
#	OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE      #
#	SOFTWARE.                                                                          #
#                                                                                          #
#   Author: sincze                                                                         #
#                                                                                          #
#   This plugin will read the status from the running inverter via the webservice.         #
#                                                                                          #
#   V 1.0.0. 25-08-2019 Initial Release                                                    #
#   V 2.0.0. 17-08-2021 Added pvoutput upload between 06:00 and 23:00                      #
############################################################################################


"""
<plugin key="GrowattWebPVO" name="Growatt Web Domoticz-Pvoutput" author="sincze" version="2.0.0" externallink="https://github.com/HarryVerjans/domoticz-growatt-webserver-pvoutput-plugin">
    <description>
        <h2>Retrieve available Growatt Inverter information from the webservice</h2><br/>
    </description>
    <params>
        <param field="Address" label="Server Address" width="200px" required="true" default="server-api.growatt.com"/>
        <param field="Mode2" label="Portal Username" width="200px" required="true" default="admin"/>
        <param field="Mode3" label="Portal Password" width="200px" required="true" password="true"/>
        <param field="Mode1" label="Protocol" width="75px">
            <options>
                <option label="HTTPS" value="443"/>
                <option label="HTTP" value="80"  default="true" />
            </options>
        </param>
        <param field="Mode4" label="Pvoutput sysids" width="200px" required="true" default="optional"/>
        <param field="Mode5" label="Pvoutput apikey" width="300px" required="true" default="optional"/>
        <param field="Mode6" label="Debug" width="150px">
            <options>
                <option label="None" value="0"  default="true" />
                <option label="Python Only" value="2"/>
                <option label="Basic Debugging" value="62"/>
                <option label="Basic+Messages" value="126"/>
                <option label="Connections Only" value="16"/>
                <option label="Connections+Python" value="18"/>
                <option label="Connections+Queue" value="144"/>
                <option label="All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""

try:
    from datetime import date								#added 2021-08-16 by HV
    from datetime import datetime							#added 2021-08-16 by HV
    import requests
    import os
    from urllib.parse import urljoin,urlencode
    import logging
    import csv
    import Domoticz
    import hashlib
    import json
    import re               # Needed to extract data from Some JSON result
    import urllib.parse     # Needed to encode request body messages

    local = False
    logfile = False
    starthour = "06"
    stophour  = "23"

except ImportError:
    local = True
    import fakeDomoticz as Domoticz
    from fakeDomoticz import Devices
    from fakeDomoticz import Parameters

class BasePlugin:
    logger = logging.getLogger(__name__)
    PVOUTPUT_URL = 'https://pvoutput.org/'
    httpConn = None
    runAgain = 6
    disconnectCount = 0
    sProtocol = "HTTP"
    cookieAvailable = False
    sessionId=""
    serverId=""
    plantId = ""
    serialnumber = ""
    pvosid = ""
    pvokey = ""

    def __init__(self):
        return

    def apiRequestHeaders(self):        # Needed headers for Login Function
        return {
            'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
            'Connection': 'keep-alive',
            'Host': 'server-api.growatt.com',
            'User-Agent': 'Domoticz/1.0',
            'Accept-Encoding': 'gzip'
        }

    def apiRequestHeaders_cookie(self): # Needed headers for Data retrieval
        return {
            'Verb': 'POST',
            'URL': '/newTwoPlantAPI.do?op=getUserCenterEnertyDataByPlantid',
            'Headers' : { 'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
                          'Connection': 'keep-alive',
                          'Host': 'server-api.growatt.com',
                          'User-Agent': 'Domoticz/1.0',
                          'Accept-Encoding': 'gzip',
                          'Cookie': ['JSESSIONID='+self.sessionId, 'SERVERID='+self.serverId]
                        },
            'Data': "plantId="+str(self.plantId)+"&language=1"
        }

# Future use
#    def apiRequestHeaders_serialnumber(self):
#        return {
#            'Verb': 'GET',
#            'URL': "/newTwoPlantAPI.do?op=getAllDeviceList&plantId="+str(self.plantId)+"&content=",
#            'Headers' : { 'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
#                          'Connection': 'keep-alive',
#                          'Host': 'server-api.growatt.com',
#                          'User-Agent': 'Domoticz/1.0',
#                          'Accept-Encoding': 'gzip',
#                          'Cookie': ['JSESSIONID='+self.sessionId, 'SERVERID='+self.serverId]
#                        },
#        }

    def onStart(self):
        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            DumpConfigToLog()

        if Parameters["Mode4"] != "":
           pvosid = Parameters["Mode4"]

        if Parameters["Mode5"] != "":
           pvokey = Parameters["Mode5"]

        # Check if devices need to be created
        createDevices()

        if (Parameters["Mode1"] == "443"): self.sProtocol = "HTTPS"
        self.httpConn = Domoticz.Connection(Name=self.sProtocol+" Test", Transport="TCP/IP", Protocol=self.sProtocol, Address=Parameters["Address"], Port=Parameters["Mode1"])
        self.httpConn.Connect()

    def onStop(self):
        Domoticz.Log("onStop - Plugin is stopping.")

    def onConnect(self, Connection, Status, Description):
        if (Status == 0):
            Domoticz.Debug("Growatt connected successfully.")
            password=Parameters["Mode3"]
            password_md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
            for i in range(0, len(password_md5), 2):
                if password_md5[i] == "0":
                    password_md5 = password_md5[0:i] + "c" + password_md5[i + 1 :]
            sendData = { 'Verb' : 'POST',
                         'URL'  : '/newTwoLoginAPI.do',
                         'Headers' : self.apiRequestHeaders(),
                         'Data': "password="+password_md5+"&userName="+urllib.parse.quote_plus(Parameters["Mode2"])
                         }
            Domoticz.Debug("Step 1. Login SendData: "+str(sendData))
            Connection.Send(sendData)
            UpdateDevice(Unit=3, nValue=1, sValue="On", TimedOut=0)         # Inverter device is on
        else:
            Domoticz.Log("Failed to connect ("+str(Status)+") to: "+Parameters["Address"]+":"+Parameters["Mode1"]+" with error: "+Description)
            UpdateDevice(Unit=3, nValue=0, sValue="Off", TimedOut=0)        # Inverter device is off

    def onMessage(self, Connection, Data):
        DumpHTTPResponseToLog(Data)
        strData = Data["Data"].decode("utf-8", "ignore")
        Status = int(Data["Status"])
        LogMessage(strData)

        if (Status == 200):
            apiResponse = json.loads(strData)
            Domoticz.Debug("Retrieved following json: "+json.dumps(apiResponse))

            try:
                if ('back' in apiResponse):
                #if not ['back']['success']:
                #    Domoticz.Log("Login Failed")
                #elif ('back' in apiResponse):
                    Domoticz.Log("Login Succesfull")
                    self.plantId = apiResponse["back"]["data"][0]["plantId"]
                    Domoticz.Log("Plant ID: "+str(self.plantId)+" was found")
                    self.ProcessCookie(Data)                                        # The Cookie is in the RAW Response, not in the JSON
                    if not self.cookieAvailable:
                        Domoticz.Debug("No cookie extracted!")
                    else:
                        Domoticz.Debug("Request Data with retrieved cookie!")
                        Connection.Send(self.apiRequestHeaders_cookie())
                elif ('powerValue' in apiResponse):
                    current = apiResponse['powerValue']
                    total = apiResponse['totalValue']                               # Convert kWh to Wh
                    etoday = apiResponse['todayValue']                              # running total today Convert kWh to Wh
                    sValue=str(current)+";"+str( float(total)*1000 )
                    Domoticz.Log("Currently producing: "+str(current)+" Watt........ Totall produced: "+str(total)+" kWh in Wh that is: "+str(float(total)*1000) )
                    UpdateDevice(Unit=1, nValue=0, sValue=sValue, TimedOut=0)
                    UpdateDevice(Unit=2, nValue=0, sValue=current, TimedOut=0)

                    acpower = str(int(float(current)))
                    yieldtodaywh = str(int(float(etoday)*1000))
                    timenow = datetime.now()
                    uploadhour = str(timenow.strftime("%H"))
                    if (uploadhour >= starthour and uploadhour < stophour):
                       if Parameters["Mode4"] != "":
                          pvoutput = uploadToPvOutput(acpower, yieldtodaywh)
                          PrintToFile(pvoutput)
                          Domoticz.Log("PVOUTPUT: "+pvoutput)
                else:
                    Domoticz.Debug("Not received anything usefull!")
            except KeyError:
                Domoticz.Debug("No defined keys found!")

        elif (Status == 400):
            Domoticz.Error("Google returned a Bad Request Error.")
        elif (Status == 500):
            Domoticz.Error("Google returned a Server Error.")
        else:
            Domoticz.Error("Google returned a status: "+str(Status))

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug("onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

    def onDisconnect(self, Connection):
        Domoticz.Log("onDisconnect called for connection to: "+Connection.Address+":"+Connection.Port)

    def onHeartbeat(self):
        #Domoticz.Trace(True)
        if (self.httpConn != None and (self.httpConn.Connecting() or self.httpConn.Connected())):
            Domoticz.Debug("onHeartbeat called, Connection is alive.")
        else:
            self.runAgain = self.runAgain - 1
            if self.runAgain <= 0:
                if (self.httpConn == None):
                    self.httpConn = Domoticz.Connection(Name=self.sProtocol+" Test", Transport="TCP/IP", Protocol=self.sProtocol, Address=Parameters["Address"], Port=Parameters["Mode1"])
                self.httpConn.Connect()
                self.runAgain = 6
            else:
                Domoticz.Debug("onHeartbeat called, run again in "+str(self.runAgain)+" heartbeats.")
        #Domoticz.Trace(False)


    def ProcessCookie(self, httpDict):
        if isinstance(httpDict, dict):
            Domoticz.Debug("Analyzing Data ("+str(len(httpDict))+"):")
            for x in httpDict:
                if isinstance(httpDict[x], dict):
                    if (x == "Headers"):
                        Domoticz.Debug("---> Headers found")
                        for y in httpDict[x]:
                            # Domoticz.Debug("------->'" + y + "':'" + str(httpDict[x][y]) + "'")
                            if (y == "Set-Cookie"):
                                Domoticz.Debug("---> Process Cookie Started")
                                try:
                                    self.sessionId = re.search(r"(?<=JSESSIONID=).*?(?=;)", str(httpDict[x][y])).group(0)
                                    Domoticz.Debug("---> SessionID found: "+ str(self.sessionId))
                                    self.cookieAvailable = True
                                except AttributeError:
                                    self.cookieAvailable = False
                                    Domoticz.Debug("---> SessionID NOT found")

                                if self.cookieAvailable:
                                    try:
                                        self.serverId = re.search(r"(?<=SERVERID=).*?(?=;)", str(httpDict[x][y])).group(0)
                                        Domoticz.Debug("---> ServerID found: "+ str(self.serverId))
                                    except AttributeError:
                                        self.cookieAvailable = False
                                        Domoticz.Debug("---> ServerID NOT found")


global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

# Generic helper functions
def LogMessage(Message):
    if Parameters["Mode6"] == "File":
        f = open(Parameters["HomeFolder"]+"http.html","w")
        f.write(Message)
        f.close()
        Domoticz.Log("File written")

def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return

def DumpHTTPResponseToLog(httpResp, level=0):
    if (level==0): Domoticz.Debug("HTTP Details ("+str(len(httpResp))+"):")
    indentStr = ""
    for x in range(level):
        indentStr += "----"
    if isinstance(httpResp, dict):
        for x in httpResp:
            if not isinstance(httpResp[x], dict) and not isinstance(httpResp[x], list):
                Domoticz.Debug(indentStr + ">'" + x + "':'" + str(httpResp[x]) + "'")
            else:
                Domoticz.Debug(indentStr + ">'" + x + "':")
                DumpHTTPResponseToLog(httpResp[x], level+1)
    elif isinstance(httpResp, list):
        for x in httpResp:
            Domoticz.Debug(indentStr + "['" + x + "']")
    else:
        Domoticz.Debug(indentStr + ">'" + x + "':'" + str(httpResp[x]) + "'")

def PrintToFile(cdata):
    # Log progress to file while debugging
    if logfile != False:
       p1_init_file="/home/pi/domoticz/plugins/domoticz-growatt-webserver-pvoutput-plugin/pvo.log"
       file=open(p1_init_file,"at")
       file.write(cdata)
       file.write('#\n')
       file.close

def UpdateDevice(Unit, nValue, sValue, TimedOut=0, AlwaysUpdate=False):
    # Make sure that the Domoticz device still exists (they can be deleted) before updating it
    if (Unit in Devices):
        if (Devices[Unit].nValue != nValue) or (Devices[Unit].sValue != sValue) or (Devices[Unit].TimedOut != TimedOut):
            Devices[Unit].Update(nValue=nValue, sValue=str(sValue), TimedOut=TimedOut)
            Domoticz.Log("Update "+str(nValue)+":'"+str(sValue)+"' ("+Devices[Unit].Name+")")
#            PrintToFile("Update "+str(nValue)+":'"+str(sValue)+"' ("+Devices[Unit].Name+")")
    return


#############################################################################
#                       Device specific functions                           #
#############################################################################

def createDevices():

    # Images
    # Check if images are in database
    if "Growatt" not in Images:
        Domoticz.Image("Growatt.zip").Create()
        image = Images["Growatt"].ID # Get id from database
        Domoticz.Log( "Image created. ID: " + str( image ) )

    # Are there any devices?
    ###if len(Devices) != 0:
        # Could be the user deleted some devices, so do nothing
        ###return

    # Give the devices a unique unit number. This makes updating them more easy.
    # UpdateDevice() checks if the device exists before trying to update it.
    if (len(Devices) == 0):
        Domoticz.Device(Name="Inverter (kWh)", Unit=1, TypeName="kWh", Used=1).Create()
        Domoticz.Log("Inverter Device kWh created.")
        Domoticz.Device(Name="Inverter (W)", Unit=2, TypeName="Usage", Used=1).Create()
        Domoticz.Log("Inverter Device (W) created.")
        Domoticz.Device(Name="Inverter Status", Unit=3, TypeName="Switch", Used=1, Image=image).Create()
        Domoticz.Log("Inverter Device (Switch) created.")


#https://pvoutput.org/help.html#api-addstatus
#https://pvoutput.org/service/r2/addstatus.jsp

#create url can be done simpler but i like this method
def build_api_url1():
    BASE_URL = os.environ.get("BASE_URL", "https://pvoutput.org/")
    path = f"/service/r2/addstatus.jsp"
    query = ''
    return urljoin(BASE_URL, path + query)

#getrealtime info api call
def uploadToPvOutput(acPower, yieldTodayWh):
    pvosid = (Parameters["Mode4"])
    pvokey = (Parameters["Mode5"])
    timenow = datetime.now()
    uploaddate = str(timenow.strftime("%Y%m%d"))
    uploadtime = str(timenow.strftime("%H:%M"))
    PrintToFile("uploadToPvoutput: "+acPower+" "+yieldTodayWh+" "+str(uploaddate)+" "+str(uploadtime))
    Domoticz.Log("PVOUTPUT "+pvosid+" "+str(uploaddate)+" "+str(uploadtime)+" "+acPower+" "+yieldTodayWh)

#    PrintToFile(pvosid)
#    PrintToFile(pvokey)

    apiUrl = build_api_url1()
    pvoutputdata = {
      'd': str(uploaddate),
      't': str(uploadtime),
      'v1': str(yieldTodayWh),
      'v2': str(acPower)
    }

    headerspv = {
        'X-Pvoutput-SystemId': str(pvosid),
        'X-Pvoutput-Apikey': str(pvokey)
    }
    try:
        response = requests.post(apiUrl, headers=headerspv, data=pvoutputdata)
        response.raise_for_status()
#        logger.debug(f'Api url: {str(apiUrl)}')
#        logger.debug(f'pvoutputdata: {str(pvoutputdata)}')
    except requests.exceptions.HTTPError as err:
        logger.exception('HTTP Error')
    except requests.exceptions.RequestException as err:
        logger.exception('Exception occurred')
#    logger.info(f'HTTP Response status code: {str(response.status_code)}')
#    logger.debug(str(response.text))
    return response.text

