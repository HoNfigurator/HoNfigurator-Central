# Server Monitoring (to be updated)
<details>
<summary>Table of Contents</summary>

  * [Overview](#overview)
  * [How Does it Work?](#how-does-it-work)
    * [Hosted by Me](#hosted-by-me)
    * [Hosted by You](#hosted-by-you)
  * [Setup](#setup)
  * [Start Monitoring!](#start-monitoring)
  * [Screenshots](#screenshots)
    * [Players Online](#players-online)
    * [Player & Server Map](#player--server-map)
    * [Lag & Uptime](#lag--uptime)
    * [Server Home Pages](#server-home-pages)
      * [Navigator & Filter](#navigator--filter)
      * [Lag Correlation to Players in-game](#lag-correlation-to-players-in-game)
      * [Server Analytics](#server-analytics)

</details>

## Overview
The following covers setting up the required agents in order to have your server monitored by ElasticSearch.

Monitoring servers provides many benefits. Some of them are listed below:
- Server Performance
    - Lag (skipped server frames)
    - Network Packet Loss (deprecated)
    - Server CPU/RAM/Disk Usage (deprecated)
    - Server Network Throughput and Disk IO (deprecated)
- Configuration Overviews
- Player and Server location plotting
- Bandwidth Estimation requirements, based on player activity on your server. (deprecated)

## How Does it Work?
### Hosted by Me
[ElasticSearch](https://www.elastic.co/what-is/elasticsearch) - Data indexing engine  
[Logstash](https://www.elastic.co/guide/en/logstash/current/introduction.html) - Data loading and transformation  
[Kibana](https://www.elastic.co/guide/en/kibana/current/introduction.html) - Dashboard Design, Data Exploration and UI

### Hosted by You

[FileBeat](https://www.elastic.co/guide/en/beats/filebeat/current/filebeat-overview.html#:~:text=Filebeat%20is%20a%20lightweight%20shipper,Elasticsearch%20or%20Logstash%20for%20indexing.) - Lightweight log collecter

[MetricBeat](https://www.google.com/search?q=what+is+metricbeat&oq=what+is+metricbeat&aqs=edge..69i57j0i512l3j0i22i30i625j0i22i30j0i22i30i625l2j69i64.2892j0j4&sourceid=chrome&ie=UTF-8) - Lightweight metrics collecter (deprecated)

---

#### 1
- Filebeat collects and ships logs for HoN Servers.
- MetricBeat collects and ships metrics for server statisics (CPU, RAM, NETWORK, IO)
- The data is sent to LogStash (hosted by me)

#### 2
- Logstash analyses, transforms (mutates and filters) the data
- Then sends it to ElasticSearch for indexing.

### 3
- Kibana aggregates the data, creating views, graphs and other pretty things.
- This is what everyone uses to monitor the servers.

## Setup
The setup is simple and should have already been completed by running HoNfigurator-Central

Registration is conducted by verifying that you are a member of the Project Kongor discord channel and have the appropriate hosting permissions.

A certificate will have been issued to your server, which it uses to authenticate and provide log files over an encrypted mutual TLS connection.

![mermaid-diagram-2023-07-19-144541](https://github.com/HoNfigurator/HoNfigurator-Central/assets/82205454/2f9958a8-58c3-4086-8e57-b81a937c3ea9)

## Start Monitoring!
Visit [HoN ElasticSearch Server Monitoring](https://hon-elk.honfigurator.app:5601)  
> Username: ``readonly``  
Password: ``Provided by me``

Start observing the fascination dashboards.

<details>
<summary>Click to see screenshots</summary>

## Screenshots
### Players Online
![image](https://user-images.githubusercontent.com/82205454/217830825-2856d990-79c4-4d5c-83df-bc68889296ad.png)

### Player & Server Map
|  Connections  |  Regions  |
| ------------ | ------------ |
|  ![image](https://user-images.githubusercontent.com/82205454/217829640-47bba280-55cb-44fc-9762-107f87a34f4e.png)  |  ![image](https://user-images.githubusercontent.com/82205454/217829442-b95f149f-be14-4419-9200-5d5911bda096.png)  |

### Lag & Uptime
|  Avg Lag per Game  |  Server Uptime  |
| ------------ | ------------ |
|  ![image](https://user-images.githubusercontent.com/82205454/217829992-7dc66aca-ed75-4ee3-8715-8eb594bdbd4f.png)  |  ![image](https://user-images.githubusercontent.com/82205454/217830278-b3b48922-5fd3-444b-bceb-081bbd1c4c73.png)  |

### Server Home Pages
#### Navigator & Filter
![image](https://user-images.githubusercontent.com/82205454/217831480-16228019-02e4-46a8-86c0-3d004461b821.png)
![image](https://user-images.githubusercontent.com/82205454/217830968-d45f3d83-b7bd-460f-850a-cfe64b91cdfd.png)

#### Lag Correlation to Players in-game
![image](https://user-images.githubusercontent.com/82205454/217831247-a45ba327-9bd9-455f-8a35-492ec9b8ff35.png)

#### Server Analytics
![image](https://user-images.githubusercontent.com/82205454/217831736-010e9b5a-91cb-486a-9411-c56b1e51565b.png)

</details>
