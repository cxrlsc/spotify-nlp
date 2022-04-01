from lyricsgenius import Genius 
import pandas as pd 
from bs4 import BeautifulSoup
import requests
import re
import os 

genres = ['country', 'r-b', 'rap', 'rock']
count = 0
seen_songs = []


def get_lyrics(): # no arguments needed
    
    global count
    
    API = "rr7YGMkarmjd_A6hUH4C_gNS46amqPOjoWUGqF1wU1UQkzwqGQ8_OHdl32h8WTrr"
    genius = Genius(API,
                    skip_non_songs=True, 
                    excluded_terms=["(Remix)", "(Live)"],
                    remove_section_headers=True) # token
    genius.timeout = 15  #timeout
    genius.sleep = 5

    for genre in genres:
        page = 5
        while page:
            try:
                res = genius.tag(genre, page=page)
                for hit in res['hits']:

                    song_dict = {'artist':[], 'title':[], 'lyrics':[], 'genre':[]}

                    url = hit['url']
                    artist = hit['artists'][0]
                    title = hit['title']

                    if title not in seen_songs:
                        print(count, artist, title)
                        seen_songs.append(title)

                        song_lyrics = genius.lyrics(song_url=url)
                        song_dict['artist'].append(artist)
                        song_dict['title'].append(title)
                        song_dict['lyrics'].append(song_lyrics)
                        song_dict['genre'].append(genre)

                        temp_data = pd.DataFrame(song_dict)

                        #if count == 0:
                        #    temp_data.to_csv('genre_lyrics.csv', index=False)
                        #else: 
                        #    temp_data.to_csv('genre_lyrics.csv', mode='a', index=False, header=False)

                        temp_data.to_csv('genre_lyrics.csv', mode='a', index=False, header=False)

                        count += 1                
                    else: 
                        continue
    
                page = res['next_page'] 
            except:
                print(page)
                break 


def main():
    
    get_lyrics()

    
if __name__ == "__main__":
    main()