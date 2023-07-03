import cv2
import mediapipe as mp
import numpy as np
import difflib
import nltk
from nltk.corpus import wordnet
from english_words import english_words
import csv
import pandas as pd
from scipy.spatial import distance

english_words = english_words

print(f"登録単語数:{len(english_words)}")

keyboard_mapping = {
    (1, 1): "Q", (2, 1): "W", (3, 1): "E", (4, 1): "R", (5, 1): "T", (6, 1): "Y", (7, 1): "U", (8, 1): "I", (9, 1): "O", (10, 1): "P",
    (1, 2): "A", (2, 2): "S", (3, 2): "D", (4, 2): "F", (5, 2): "G", (6, 2): "H", (7, 2): "J", (8, 2): "K", (9, 2): "L", (10, 2): ";",
    (1, 3): "Z", (2, 3): "X", (3, 3): "C", (4, 3): "V", (5, 3): "B", (6, 3): "N", (7, 3): "M", (8, 3): ",", (9, 3): ".", (10, 3): "/"
}

# Load previously saved trajectories
try:
    df_trajectory = pd.read_csv('trajectory.csv', header=None, names=['word', 'similarity', 'trajectory'])
    df_trajectory['trajectory'] = df_trajectory['trajectory'].apply(eval)  # Convert string representation of list to list
    df_trajectory = df_trajectory.dropna(subset=['trajectory'])  # Remove rows with missing trajectory values
except FileNotFoundError:
    df_trajectory = pd.DataFrame(columns=['word', 'similarity', 'trajectory'])

cv2.namedWindow("Main", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Main", 800, 600)

mp_drawing = mp.solutions.drawing_utils
mp_hands = mp.solutions.hands

cap = cv2.VideoCapture(0)
frame_rate = 30
cap.set(cv2.CAP_PROP_FPS, frame_rate)

trajectory = []
is_count_start_number = 5
num_elements = 10 # 配列の記録要素数

def average_elements_interval(arr):
    if len(arr) >= num_elements:
        return np.mean(arr[:num_elements], axis=0)

    repeated_array = np.tile(arr, (num_elements // len(arr) + 1, 1))[:num_elements]
    interval = len(repeated_array) // num_elements
    averaged_array = np.mean(repeated_array.reshape(-1, interval), axis=1)
    return averaged_array

def find_trajectory_similarity(input_trajectory):
    input_trajectory = np.array(input_trajectory)
    input_trajectory = average_elements_interval(input_trajectory)
    input_trajectory = input_trajectory.flatten()  # 1次元のベクトルに変換
    trajectory_similarity = []
    for idx, row in df_trajectory.iterrows():
        saved_trajectory = np.array(row['trajectory'])
        saved_trajectory = saved_trajectory.flatten()  # 1次元のベクトルに変換
        if len(saved_trajectory) != len(input_trajectory):
            continue
        similarity = -distance.euclidean(input_trajectory, saved_trajectory)  # ユークリッド距離を計算
        trajectory_similarity.append(similarity)

    return trajectory_similarity



def calculate_next_word(sentence, new_words):
    tokens = nltk.word_tokenize(sentence)
    tagged_tokens = nltk.pos_tag(tokens)
    nouns = [token for token, tag in tagged_tokens if tag.startswith('NN')]

    max_similarity = 0
    next_word = new_words[0]

    for new_word in new_words:
        new_word_synsets = wordnet.synsets(new_word)
        if new_word_synsets:
            for noun in nouns:
                noun_synsets = wordnet.synsets(noun)
                if noun_synsets:
                    similarity = noun_synsets[0].wup_similarity(new_word_synsets[0])
                    if similarity is not None and similarity > max_similarity:
                        max_similarity = similarity
                        next_word = new_word

    return next_word

suggestion_word_num = 100

def find_closest_words(input_string):
    closest_words = []
    similarities = []

    print(f"入力結果: {input_string}")

    trajectory_similarities = find_trajectory_similarity(trajectory)
    print("trajectory similarity detected:",trajectory_similarities)

    for word in english_words:
        similarity = difflib.SequenceMatcher(None, input_string, word).ratio()
        
        if word in trajectory_similarities:
            print("find")
            similarity = max(similarities) + (max(similarities) - similarity) * (1 - i / suggestion_word_num)

        if len(closest_words) < suggestion_word_num:
            closest_words.append(word)
            similarities.append(similarity)
        else:
            min_similarity = min(similarities)
            min_index = similarities.index(min_similarity)
            if similarity > min_similarity:
                closest_words[min_index] = word
                similarities[min_index] = similarity

    sorted_words = [x for _, x in sorted(zip(similarities, closest_words), reverse=True)]
    
    print("keyboard similarity detected:", sorted_words)

    return sorted_words, similarities

def smooth_trajectory(trajectory, window_size=5):
    smoothed_trajectory = []
    for i in range(len(trajectory)):
        start_idx = max(0, i - window_size)
        end_idx = min(len(trajectory), i + window_size + 1)
        window = trajectory[start_idx:end_idx]
        smoothed_point = np.mean(window, axis=0)
        smoothed_trajectory.append(smoothed_point)
    return smoothed_trajectory

def remove_repeated_characters(input_string):
    if len(input_string) <= 1:
        return input_string
    
    result = input_string[0] + input_string[1]
    for i in range(2, len(input_string)):
        if input_string[i] != input_string[i-1]:
            result += input_string[i]
    
    return result

sub_trajectory_length = 10

def generate_word_suggestion(trajectory, image):

    word_suggestion = ""
    trajectory = smooth_trajectory(trajectory)
    averaged_trajectory = []
    for i in range(0, len(trajectory), sub_trajectory_length):
        sub_trajectory = trajectory[i:i+sub_trajectory_length]
        if len(sub_trajectory) == sub_trajectory_length:
            avg_x = sum(point[0] for point in sub_trajectory) // sub_trajectory_length
            avg_y = sum(point[1] for point in sub_trajectory) // sub_trajectory_length
            averaged_trajectory.append((avg_x, avg_y))
            key = (avg_x // (image.shape[1] // 10) + 1, avg_y // (image.shape[0] // 5) + 1)
            if key in keyboard_mapping:
                word_suggestion += keyboard_mapping[key]

    word_suggestion = remove_repeated_characters(word_suggestion)
    word_suggestion = word_suggestion.lower()

    sorted_words, similarities = find_closest_words(word_suggestion)

    return sorted_words, similarities, averaged_trajectory

threshold_angle = 15
straight_counter = 0
straight_frame_threshold = 10
word_suggestions = ""
sentence = ""

hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# Open or create trajectory.csv file
try:
    with open('trajectory.csv', 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
except IOError:
    print("I/O error")

try:
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            print("カメラからのキャプチャができませんでした。")
            break

        frame = cv2.flip(frame, 1)

        image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(image)

        if not results:
            straight_counter = 0

        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                mp_drawing.draw_landmarks(
                    image, hand_landmarks, mp_hands.HAND_CONNECTIONS)

            for key, value in keyboard_mapping.items():
                x = (key[0] - 1) * (image.shape[1] // 10)
                y = (key[1] - 1) * (image.shape[0] // 5)
                overlay = image.copy()
                cv2.rectangle(overlay, (x, y), (x + (image.shape[1] // 10), y + (image.shape[0] // 5)), (255, 255, 255), -1)
                alpha = 0.2
                image = cv2.addWeighted(overlay, alpha, image, 1 - alpha, 0)
                if key in trajectory:
                    cv2.putText(image, value, (x + 20, y + 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                else:
                    cv2.putText(image, value, (x + 20, y + 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)

            for id, landmark in enumerate(hand_landmarks.landmark):
                if id == 8 and landmark.y < hand_landmarks.landmark[5].y:
                    straight_counter += 1
                    if straight_counter >= straight_frame_threshold:
                        x = int(landmark.x * image.shape[1])
                        y = int(landmark.y * image.shape[0])
                        trajectory.append((x, y))
                        if len(trajectory) > is_count_start_number:
                            for i in range(1, len(trajectory)):
                                cv2.line(image, trajectory[i-1], trajectory[i], (0, 0, 255), 3)

                elif id == 8 and landmark.y > hand_landmarks.landmark[5].y:
                    if len(trajectory) > is_count_start_number:
                        word_suggestion, similarities, averaged_trajectory = generate_word_suggestion(trajectory, image)
                        print("出力結果:", word_suggestion)
                        word_suggestions = ""
                        for id, word in enumerate(word_suggestion):
                            word_suggestions += f"{id+1}:{word} "

                        # Get correct word input from user
                        correct_word = input("正解の単語を入力してください: ")
                        similarity = 0
                        if correct_word in word_suggestion:
                            index = word_suggestion.index(correct_word)
                            similarity = similarities[index]
                        
                        # Append the result to the trajectory.csv file
                        if trajectory:
                            with open('trajectory.csv', 'a', newline='') as csvfile:
                                writer = csv.writer(csvfile)
                                print_out_text = [correct_word, similarity, averaged_trajectory]  # Store averaged trajectory as list
                                print("print_out:", print_out_text)
                                writer.writerow(print_out_text)
                        trajectory = []

                    else:
                        trajectory = []

        cv2.putText(image, word_suggestions, (10, 450), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (250,104,0), 2)
        # cv2.putText(image, sentence, (10, 450), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (109,135,100), 4)
        cv2.imshow('Main', image)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        if cv2.waitKey(1) & 0xFF == ord('r'):
            sentence = ""
            word_suggestions = ""
finally:
    hands.close()
    cap.release()
    cv2.destroyAllWindows()
