""" 
Název: Detekce pokerových karet v rukách hráčů
Autor: Vladyslav Kovalets
Popis: Skript slouží k detekci pokerových karet v rukách hráče. 
       Zpracovává video z kamery zabudované do hrany stolu, která zachycuje moment,
       kdy se hráč dívá na své karty. Skript akceptuje jako vstup buďto jedno video,
       nebo více videí z jedné hry. V případě výběru více videí z jedné hry se předpokládá,
       že každé video zachycuje akce jiného hráče u stolu.

Vstup:
    --source - cesta k videu nebo videím ve formátu MP4.

Výstup:
    - Textový soubor s seznamem detekovaných karet.
    - Výstupní video s vloženými ikonami detekovaných karet.
    - JSON soubor obsahující detailní informace o detekovaných kartách 
      včetně typu karty, souřadnic a jistoty rozpoznání.
"""

import torch
import cv2
import json
import os
import argparse


def load_model():
    """
    Načtení a vrácení YOLOv5 modelu z určené cesty. Model je připraven pro použití s GPU.

    Vrací:
        model: YOLOv5 model pro detekci karet.
    """

    model = torch.hub.load('ultralytics/yolov5', 'custom', path='model/poker_card_detector.pt')
    model = model.cuda()
    return model


def load_card_images(card_images_dir):
    """
    Načtení všech ikon karet a vrácení slovníku s názvy karet a jejich obrázky.

    Parametry:
        card_images_dir: Cesta k adresáři s ikonami karet.

    Vrací:
        card_images: Slovník s názvy karet a jejich obrázky.
    """

    card_images = {}
    for card_name in os.listdir(card_images_dir):
        if card_name.endswith('.png'):
            card = card_name[:-4]
            card_image_path = os.path.join(card_images_dir, card_name)
            card_images[card] = cv2.imread(card_image_path, cv2.IMREAD_UNCHANGED)
    return card_images


def process_video(video_path, model, card_images, card_ids, data, output_base_path):
    """
    Zpracování videa, detekce karet a zápis výsledků do JSON a výstupního videa.

    Parametry:
        video_path: Cesta k vstupnímu videu.
        model: YOLOv5 model pro detekci karet.
        card_images: Slovník s názvy karet a jejich obrázky.
        card_ids: Slovník s názvy karet a jejich ID.
        data: JSON data pro záznam informací o detekcích.
        output_base_path: Cesta k adresáři pro uložení výstupních souborů.
    """
    
    # Načtení videa a získání informací o šířce, výšce a FPS.
    cap = cv2.VideoCapture(video_path) 
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) 
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = int(cap.get(cv2.CAP_PROP_FPS)) 
    output_video_path = os.path.join(output_base_path, os.path.basename(video_path))

    # Nastavení výstupního videa pro záznam s určenou šířkou, výškou a FPS. 
    out = setup_video_io(frame_width, frame_height, fps, output_video_path)
    
    total_frames = 0
    card_frequency = {name: 0 for name in card_ids}

    # Zpracování každého snímku videa.
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        total_frames += 1
        frame_data = analyze_frame(cap, frame, model, card_images, card_ids)
        for card_info in frame_data["cards_info"]:
            card_frequency[card_info["name"]] += 1
        data["frames"].append(frame_data)
        modified_frame = render_results_on_frame(frame, frame_data, card_images)
        out.write(modified_frame)

    cap.release()
    out.release()

    # Přidání informací o videu do výsledného JSON.
    data["video_data"].append({
        "video": os.path.basename(video_path),
        "card_frequency": card_frequency,
        "total_frames": total_frames
    })


def setup_video_io(frame_width, frame_height, fps, output_video_path):
    """
    Nastavení výstupního videa pro záznam s určenou šířkou, výškou a FPS. Využívá kodek 'mp4v'.

    Parametry:
        frame_width: Šířka snímku videa.
        frame_height: Výška snímku videa.
        fps: FPS videa.
        output_video_path: Cesta k výstupnímu videu.

    Vrací:
        out: VideoWriter pro záznam výstupního videa.
    """

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_video_path, fourcc, fps, (frame_width, frame_height))
    if not out.isOpened():
        print("Failed to open video writer. Check codec compatibility and output path.")
        exit(1)
    return out


def analyze_frame(cap, frame, model, card_images, card_ids):
    """
    Analýza snímku videa, detekce karet a vytvoření informací o detekci.
    
    Parametry:
    
        cap: VideoCapture pro získání informací o snímku.
        frame: Snímek videa pro analýzu.
        model: YOLOv5 model pro detekci karet.
        card_images: Slovník s názvy karet a jejich obrázky.
        card_ids: Slovník s názvy karet a jejich ID.
        
    Vrací:
        frame_data: Informace o detekcích karet na snímku.
    """

    # Získání informací o snímku.
    frame_id = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
    frame_time = round(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0, 2)
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = model(frame_rgb)
    frame_data = {"frame_id": frame_id, "timestamp": frame_time, "cards_detected_one_corner": [], "cards_detected_two_corners": [], "cards_info": []}
    card_counts = {}

    # Zpracování detekcí karet a vytvoření informací pro každou detekci.
    for detection in results.xyxy[0]:
        bbox = detection[:4].tolist()
        class_index = int(detection[5])
        class_name = model.names[class_index]
        confidence = float(detection[4])
        # Přidání informací o kartě, pokud má detekce dostatečnou jistotu.
        if confidence >= 0.8:
            card_info = {
                "card_id": card_ids[class_name],
                "name": class_name,
                "x_coord": round(bbox[0], 2),
                "y_coord": round(bbox[1], 2),
                "confidence": round(confidence, 2)
            }
            frame_data["cards_info"].append(card_info)
            card_counts[class_name] = card_counts.get(class_name, 0) + 1

    # Seřazení detekcí karet podle X souřadnice a vytvoření seznamů karet s jedním a dvěma detekovanými rohy.
    temp_cards_detected_two_corners = [name for name, count in card_counts.items() if count == 2]
    sorted_cards = sorted(temp_cards_detected_two_corners, key=lambda name: next(card["x_coord"] for card in frame_data["cards_info"] if card["name"] == name))
    frame_data["cards_detected_two_corners"] = sorted_cards

    cards_detected_one_corner = [name for name, count in card_counts.items() if count == 1]
    frame_data["cards_detected_one_corner"] = cards_detected_one_corner

    return frame_data


def render_results_on_frame(frame, frame_data, card_images):
    """
    Vykreslení výsledků detekce karet na snímku včetně ikon karet.

    Parametry:
        frame: Snímek videa pro vykreslení výsledků.
        frame_data: Informace o detekcích karet na snímku.
        card_images: Slovník s názvy karet a jejich obrázky.

    Vrací:
        frame: Snímek videa s vloženými ikonami detekovaných karet.
    """
    
    # Vykreslení ID snímku.
    frame_id = frame_data['frame_id']
    cv2.putText(frame, f'Frame: {frame_id}', (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
    
    start_y = 70
    draw_position_index = 0
    already_drawn_cards = set()
    cards_sorted_by_x = sorted(frame_data["cards_info"], key=lambda card: card["x_coord"])

    # Vykreslení ikon karet na snímek podle jejich X souřadnice.
    for card_info in cards_sorted_by_x:
        card_name = card_info["name"]
        if card_name not in already_drawn_cards and card_name in card_images:
            already_drawn_cards.add(card_name)
            card_image = card_images[card_name]
            start_x = 10 + draw_position_index * (card_image.shape[1] + 10)
            alpha_s = card_image[:, :, 3] / 255.0
            alpha_l = 1.0 - alpha_s
            for c in range(0, 3):
                frame[start_y:start_y+card_image.shape[0], start_x:start_x+card_image.shape[1], c] = \
                    (alpha_s * card_image[:, :, c] + alpha_l * frame[start_y:start_y+card_image.shape[0], start_x:start_x+card_image.shape[1], c])
            draw_position_index += 1

    return frame 


def read_data_from_json(json_path):
    """
    Načtení dat z JSON souboru a vrácení načtených dat.

    Parametry:
        json_path: Cesta k JSON souboru.

    Vrací:  
        json_data: Načtená data z JSON souboru.
    """

    with open(json_path, 'r') as file:
        return json.load(file)


def write_cards_to_file_from_json(json_data, output_txt_path, min_appearance):
    """
    Záznam informací o kartách do textového souboru na základě JSON dat.

    Parametry:
        json_data: Načtená data z JSON souboru.
        output_txt_path: Cesta k výstupnímu textovému souboru.
        min_appearance: Minimální počet výskytů karty pro zahrnutí do výsledného seznamu.
    """

    with open(output_txt_path, 'w', encoding='utf-8') as txt_file:
        player_index = 1
        for video_info in json_data["video_data"]:
            card_frequency = video_info["card_frequency"]
            # Výběr karet, které se vyskytly alespoň 'min_appearance' krát.
            valid_cards = [card for card, count in card_frequency.items() if count >= min_appearance]
            if len(valid_cards) > 2:
                valid_cards = valid_cards[:2]  

            card_description = ', '.join(valid_cards)
            txt_file.write(f"Hráč {player_index}: {card_description}.\n")
            player_index += 1


def main():
    """
    Spuštění celého procesu zpracování videa, od načtení modelu po ukládání výsledků.
    """

    parser = argparse.ArgumentParser(description='Process video files.')
    parser.add_argument('--source', nargs='+', help='Paths to the input video files', required=True)
    args = parser.parse_args()

    model = load_model()
    card_names = [
        '10C', '10D', '10H', '10S', '2C', '2D', '2H', '2S', '3C', '3D', '3H', '3S', '4C',
        '4D', '4H', '4S', '5C', '5D', '5H', '5S', '6C', '6D', '6H', '6S', '7C', '7D', 
        '7H', '7S', '8C', '8D', '8H', '8S', '9C', '9D', '9H', '9S', 'AC', 'AD', 'AH',
        'AS', 'JC', 'JD', 'JH', 'JS', 'KC', 'KD', 'KH', 'KS', 'QC', 'QD', 'QH', 'QS']
    card_images_dir = 'card_icons' 
    output_base_path = 'output/players'
    json_file_name = 'framewise_detected_players_cards.json'
    txt_file_name = 'players_cards_list.txt'
    # Minimální počet výskytů karty pro zahrnutí do výsledného seznamu.
    min_appearance = 5 
    card_images = load_card_images(card_images_dir)
    
    card_ids = {name: idx + 1 for idx, name in enumerate(card_names)} 
    data = {"frames": [], "video_data": []} 
    
    # Zpracování všech zadaných videí.
    for video_path in args.source:
        print(f"Processing video: {video_path}")
        process_video(video_path, model, card_images, card_ids, data, output_base_path)
        new_video_path = os.path.join(output_base_path, os.path.basename(video_path))
        print(f"Processed video saved to {new_video_path}")

    # Uložení výsledků do JSON a textového souboru.
    output_json_path = os.path.join(output_base_path, json_file_name)
    with open(output_json_path, 'w') as json_file:
        json.dump(data, json_file, indent=4)
    print(f"Detected cards information saved to {output_json_path}")

    json_data = read_data_from_json(output_json_path)
    output_txt_path = os.path.join(output_base_path, txt_file_name)
    write_cards_to_file_from_json(json_data, output_txt_path, min_appearance)
    print(f"List of cards saved to {output_txt_path}")

if __name__ == '__main__':
    main()