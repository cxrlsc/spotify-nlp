from lyricsgenius import Genius
import pandas as pd
from bs4 import BeautifulSoup
import requests
import re
import os


URL = "https://www.udiscovermusic.com/artists-a-z/"
content = requests.get(URL)
soup = BeautifulSoup(content.text, 'html.parser')
row = soup.find_all('a', class_='artist-page-link')
artist_names = [r.get_text() for r in row]
seen_artists = []
count = 143
artist_names = artist_names[count:]


def extract_songs_data(songs):
    tbl = pd.DataFrame()
    for song in songs:
        song_dict = song.to_dict()
        song_artist = song_dict["primary_artist"]["name"]
        song_title = song_dict["title"]
        song_lyrics = song_dict["lyrics"]
        song_descpt = song_dict["description"]
        song_release_date = song_dict["release_date_for_display"]

        temp_data = pd.DataFrame({
            'artist': song_artist,
            'title': song_title,
            'lyrics': song_lyrics,
            'description': song_descpt,
            'release date': song_release_date
        })
        
        tbl = tbl.append(temp_data, ignore_index=True)
        
    return tbl

    

def get_songs(data, num_songs, genius, token, artist_lst_copy):
    global count 
    def run(data, artist, num_songs, genius, token, artist_lst_copy):
        global count
        try:
            if artist not in seen_artists:
                songs = genius.search_artist(artist, max_songs=num_songs, sort="popularity").songs
                new_data = extract_songs_data(songs)

                data = data.append(new_data, ignore_index=True)
                artist_just_seen = artist_lst_copy.pop(0)
                seen_artists.append(artist_just_seen)

                if count == 0:
                    data.to_csv('big_lyrics_new.csv', index=False)
                else: 
                    data.to_csv('big_lyrics_new_two.csv', mode='a', index=False, header=False)

            else:
                pass
            
        except AttributeError:
            print("No songs found")
            artist_just_seen = artist_lst_copy.pop(0)
            seen_artists.append(artist_just_seen)
        
        count += 1
        return
        
    for i in range(len(artist_lst_copy)): 
        artist = artist_lst_copy[0]
        try: 
            run(data, artist, num_songs, genius, token, artist_lst_copy)
        except: 
            run(data, artist, num_songs, genius, token, artist_lst_copy)
            
            
def main():
    df = pd.DataFrame({
        'artist': [],
        'title': [],
        'lyrics': [],
        'description': [],
        'release date': []
    })
    
    
    while len(artist_names) > 0:
        try: 
            token = "rr7YGMkarmjd_A6hUH4C_gNS46amqPOjoWUGqF1wU1UQkzwqGQ8_OHdl32h8WTrr"

            genius = Genius(token, 
                            skip_non_songs=True, 
                            excluded_terms=["(Remix)", "(Live)"], 
                            remove_section_headers=True)


            get_songs(df, 7, genius, token, artist_names)
        except: 
            token = "rr7YGMkarmjd_A6hUH4C_gNS46amqPOjoWUGqF1wU1UQkzwqGQ8_OHdl32h8WTrr"
            genius = Genius(token, 
                            skip_non_songs=True, 
                            excluded_terms=["(Remix)", "(Live)"], 
                            remove_section_headers=True)


            get_songs(df, 7, genius, token, artist_names)

    return count

if __name__ == "__main__":
    while len(artist_names) > 0:
        try:
            main()
        except:
            main()


