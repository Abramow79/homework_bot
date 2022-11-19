import logging
import os
import sys
import time
from http import HTTPStatus
from logging import Formatter, StreamHandler

import requests
import telegram
from dotenv import load_dotenv

from exceptions import (EndpointError, EndpointStatusError, NotForSendingError,
                        SendMessageError)

load_dotenv()

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_TIME = 480
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
ERROR_BY_SENDING = (
    f'Ошибка при отправке сообщения: {telegram.error.TelegramError}'
)
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_STATUSES = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = StreamHandler(stream=sys.stdout)
logger.addHandler(handler)
formatter = Formatter(
    '%(asctime)s, %(levelname)s, %(name)s, '
    '%(funcName)s, %(levelno)s, %(message)s'
)
handler.setFormatter(formatter)


def send_message(bot, message):
    """Отправляет сообщения в Telegram."""
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except telegram.error.TelegramError:
        logger.error(ERROR_BY_SENDING, exc_info=True)
        raise SendMessageError(ERROR_BY_SENDING)


def get_api_answer(current_timestamp):
    """Делает запрос к API сервиса Практикум.Домашка."""
    PARAMS = {'from_date': current_timestamp or int(time.time())}
    ADDRESS_NOT_AVAILABLE = (
        f'Адрес {ENDPOINT} c параметрами: {PARAMS} недоступен'
    )
    ERROR_BY_REQUEST_TO_ENDPOINT = (
        f'Проблема при обращении к {ENDPOINT}.'
        'Ошибка {requests.exceptions.RequestException}'
    )
    try:
        api_response = requests.get(ENDPOINT, headers=HEADERS, params=PARAMS)
        if api_response.status_code != HTTPStatus.OK:
            logger.error(ADDRESS_NOT_AVAILABLE)
            raise EndpointStatusError(ADDRESS_NOT_AVAILABLE)
        return api_response.json()
    except requests.exceptions.RequestException:
        logger.error(ERROR_BY_REQUEST_TO_ENDPOINT, exc_info=True)
        raise EndpointError(ERROR_BY_REQUEST_TO_ENDPOINT)


def check_response(response):
    """Проверяет ответ API на корректность."""
    API_RESPONSE_NOT_DICT_TYPE = (
        f'Тип данных ответа API не является словарём: {response}'
    )
    if not isinstance(response, dict):
        logger.error(API_RESPONSE_NOT_DICT_TYPE)
        raise TypeError(API_RESPONSE_NOT_DICT_TYPE)
    elif 'homeworks' not in response:
        HOMEWORK_KEY_NOT_IN_API_RESPONSE = (
            'Ключ homeworks отсутствует в ответе API.'
            f'Ключи ответа: {response.keys()}'
        )
        logger.error(HOMEWORK_KEY_NOT_IN_API_RESPONSE)
        raise KeyError(HOMEWORK_KEY_NOT_IN_API_RESPONSE)
    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        TYPE_OF_HOMEWORKS_KEY_NOT_LIST_TYPE = (
            'Тип данных значения по ключу homeworks не является списком: '
            f'{homeworks}'
        )
        logger.error(TYPE_OF_HOMEWORKS_KEY_NOT_LIST_TYPE)
        raise TypeError(TYPE_OF_HOMEWORKS_KEY_NOT_LIST_TYPE)
    elif not homeworks:
        logger.debug('Статус проверки домашнего задания не обновлялся')
        return homeworks
    return homeworks[0]


def parse_status(homework):
    """Достает статус проверки домашнего задания."""
    for key in ('homework_name', 'status'):
        REQUIRED_KEY_FOR_STATUS_DETERMING_MISSED = (
            'Отсутствует необходимый ключ для определения статуса '
            f'проверки домашнего задания: {key}'
        )
        if key not in homework:
            logger.error(REQUIRED_KEY_FOR_STATUS_DETERMING_MISSED)
            raise KeyError(REQUIRED_KEY_FOR_STATUS_DETERMING_MISSED)
    homework_name = homework['homework_name']
    homework_status = homework['status']
    if homework_status not in HOMEWORK_STATUSES:
        UNDOCUMENTED_HOMEWORKS_CHECK_STATUS = (
            'Незадокументированный статус проверки домашней работы: '
            f'{homework_status}'
        )
        logger.error(UNDOCUMENTED_HOMEWORKS_CHECK_STATUS)
        raise KeyError(UNDOCUMENTED_HOMEWORKS_CHECK_STATUS)
    verdict = HOMEWORK_STATUSES[homework_status]
    return f'Изменился статус проверки работы "{homework_name}": {verdict}'


def check_tokens():
    """Проверяет доступность переменных окружения."""
    variables_data = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
    }
    no_value = [
        var_name for var_name, value in variables_data.items() if not value
    ]
    if no_value:
        logger.critical(
            'Отсутствуют необходимые переменные окружения: '
            f'{no_value}.Программа принудительно остановлена'
        )
        return False
    logger.info('Переменные окружения доступны')
    return True


def main():
    """Основная логика работы бота."""
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    current_timestamp = int(time.time())
    error_message = ''
    homework_status_message = ''
    while True:
        try:
            response = get_api_answer(current_timestamp)
            homework = check_response(response)
            current_timestamp = response.get('current_date', current_timestamp)
            if homework:
                status_homework = parse_status(homework)
                if status_homework not in homework_status_message:
                    homework_status_message = status_homework
                    send_message(bot, homework_status_message)
        except NotForSendingError as error:
            message = f'Поизошла ошибка при обращении к Telegram: {error}'
            logger.error(message, exc_info=True)
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            if message not in error_message:
                error_message = message
                logger.error(message, exc_info=True)
                send_message(bot, message)

        time.sleep(RETRY_TIME)


if __name__ == "__main__":
    if check_tokens():
        main()
    sys.exit(
        'Отсутствуют необходимые переменные окружения.'
        'Программа принудительно остановлена. Подробности в логах.'
    )
