# ruff: noqa: RUF001 - Telugu/Hindi text: "ambiguous" characters are the real script.
"""Every patient-facing string of the booking bot, in Telugu, Hindi and English.

Button titles must fit WhatsApp's 20 characters and list rows 24 (checked by tests).
Placeholders use str.format names.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.conversation.types import Language

CATALOG: dict[str, dict[Language, str]] = {
    "menu": {
        "te": "మీకు ఎలా సహాయం చేయగలను?",
        "hi": "मैं आपकी कैसे मदद कर सकता हूँ?",
        "en": "How can I help you?",
    },
    "btn_book": {"te": "అపాయింట్‌మెంట్ బుక్", "hi": "अपॉइंटमेंट बुक करें", "en": "Book appointment"},
    "btn_my": {"te": "నా అపాయింట్‌మెంట్లు", "hi": "मेरे अपॉइंटमेंट", "en": "My appointments"},
    "btn_reception": {"te": "రిసెప్షన్ సహాయం", "hi": "रिसेप्शन से बात", "en": "Talk to reception"},
    "who": {
        "te": "అపాయింట్‌మెంట్ ఎవరి కోసం?",
        "hi": "अपॉइंटमेंट किसके लिए है?",
        "en": "Who is the appointment for?",
    },
    "row_someone_else": {"te": "వేరే వ్యక్తి", "hi": "कोई और", "en": "Someone else"},
    "list_choose": {"te": "ఎంచుకోండి", "hi": "चुनें", "en": "Choose"},
    "ask_name": {
        "te": "రోగి పూర్తి పేరు టైప్ చేయండి.",
        "hi": "कृपया मरीज़ का पूरा नाम लिखें।",
        "en": "Please type the patient's full name.",
    },
    "bad_name": {
        "te": "దయచేసి సరైన పేరు పంపండి.",
        "hi": "कृपया सही नाम भेजें।",
        "en": "Please send a valid name.",
    },
    "doctor": {"te": "డాక్టర్‌ను ఎంచుకోండి.", "hi": "डॉक्टर चुनें।", "en": "Choose a doctor."},
    "no_doctors": {
        "te": "ప్రస్తుతం ఆన్‌లైన్ బుకింగ్ అందుబాటులో లేదు. రిసెప్షన్ మిమ్మల్ని సంప్రదిస్తుంది.",
        "hi": "अभी ऑनलाइन बुकिंग उपलब्ध नहीं है। रिसेप्शन आपसे संपर्क करेगा।",
        "en": "Online booking is not available right now. Reception will contact you.",
    },
    "date": {
        "te": "{doctor} గారి కోసం రోజును ఎంచుకోండి.",
        "hi": "{doctor} के लिए दिन चुनें।",
        "en": "Choose a day for {doctor}.",
    },
    "slots_count": {"te": "{n} ఖాళీలు", "hi": "{n} स्लॉट खाली", "en": "{n} free slots"},
    "no_dates": {
        "te": "రాబోయే 7 రోజుల్లో {doctor} గారికి ఖాళీ లేదు. వేరే డాక్టర్‌ను ఎంచుకోండి.",
        "hi": "अगले 7 दिनों में {doctor} के पास कोई स्लॉट खाली नहीं है। कोई और डॉक्टर चुनें।",
        "en": "{doctor} has no free slots in the next 7 days. Please choose another doctor.",
    },
    "slot": {
        "te": "{day} సమయం ఎంచుకోండి.",
        "hi": "{day} का समय चुनें।",
        "en": "Choose a time on {day}.",
    },
    "row_more": {"te": "మరిన్ని", "hi": "और विकल्प", "en": "More options"},
    "reason": {
        "te": "ఏ కారణంతో వస్తున్నారు? (ఐచ్ఛికం)",
        "hi": "किस कारण से आ रहे हैं? (वैकल्पिक)",
        "en": "What is the visit for? (optional)",
    },
    "reason_general": {"te": "సాధారణ పరీక్ష", "hi": "सामान्य जाँच", "en": "General check-up"},
    "reason_fever": {"te": "జ్వరం / జలుబు", "hi": "बुखार / सर्दी", "en": "Fever / cold"},
    "reason_followup": {"te": "ఫాలో-అప్", "hi": "फॉलो-अप", "en": "Follow-up visit"},
    "reason_pain": {"te": "నొప్పి", "hi": "दर्द", "en": "Pain"},
    "reason_child": {"te": "పిల్లల ఆరోగ్యం", "hi": "बच्चे का स्वास्थ्य", "en": "Child health"},
    "reason_other": {"te": "ఇతర", "hi": "अन्य", "en": "Other"},
    "reason_skip": {"te": "వదిలేయండి", "hi": "छोड़ें", "en": "Skip"},
    "confirm": {
        "te": "దయచేసి నిర్ధారించండి:\nరోగి: {patient}\nడాక్టర్: {doctor}\nరోజు: {day}\nసమయం: {time}",
        "hi": "कृपया पुष्टि करें:\nमरीज़: {patient}\nडॉक्टर: {doctor}\nदिन: {day}\nसमय: {time}",
        "en": "Please confirm:\nPatient: {patient}\nDoctor: {doctor}\nDay: {day}\nTime: {time}",
    },
    "btn_confirm": {"te": "నిర్ధారించు", "hi": "पुष्टि करें", "en": "Confirm"},
    "btn_change": {"te": "మార్చు", "hi": "बदलें", "en": "Change"},
    "requested": {
        "te": "అభ్యర్థన అందింది. రిసెప్షన్ త్వరలో నిర్ధారిస్తుంది.",
        "hi": "अनुरोध मिल गया। रिसेप्शन जल्द ही पुष्टि करेगा।",
        "en": "Request received. Reception will confirm shortly.",
    },
    "slot_taken": {
        "te": "క్షమించండి, ఆ సమయం ఇప్పుడే బుక్ అయింది. తదుపరి ఖాళీ సమయాలు ఇవి.",
        "hi": "माफ़ कीजिए, वह समय अभी बुक हो गया। ये अगले खाली समय हैं।",
        "en": "Sorry, that time was just taken. Here are the next free times.",
    },
    "booking_failed": {
        "te": "క్షమించండి, బుక్ చేయలేకపోయాను. రిసెప్షన్ మీకు సహాయం చేస్తుంది.",
        "hi": "माफ़ कीजिए, बुकिंग नहीं हो सकी। रिसेप्शन आपकी मदद करेगा।",
        "en": "Sorry, I couldn't book that. Reception will help you.",
    },
    "my_none": {
        "te": "మీకు రాబోయే అపాయింట్‌మెంట్లు లేవు.",
        "hi": "आपका कोई आने वाला अपॉइंटमेंट नहीं है।",
        "en": "You have no upcoming appointments.",
    },
    "my_list": {
        "te": "మీ రాబోయే అపాయింట్‌మెంట్లు:",
        "hi": "आपके आने वाले अपॉइंटमेंट:",
        "en": "Your upcoming appointments:",
    },
    "status_pending": {"te": "నిర్ధారణ కోసం", "hi": "पुष्टि बाकी", "en": "awaiting confirmation"},
    "status_scheduled": {"te": "నిర్ధారించబడింది", "hi": "पक्का", "en": "confirmed"},
    "appt_action": {
        "te": "{summary}\nఏమి చేయాలి?",
        "hi": "{summary}\nआप क्या करना चाहेंगे?",
        "en": "{summary}\nWhat would you like to do?",
    },
    "btn_cancel_appt": {"te": "రద్దు చేయి", "hi": "रद्द करें", "en": "Cancel"},
    "btn_reschedule": {"te": "సమయం మార్చు", "hi": "समय बदलें", "en": "Reschedule"},
    "btn_back": {"te": "వెనుకకు", "hi": "वापस", "en": "Back"},
    "cancel_confirm": {
        "te": "ఈ అపాయింట్‌మెంట్ రద్దు చేయాలా?",
        "hi": "क्या यह अपॉइंटमेंट रद्द करें?",
        "en": "Cancel this appointment?",
    },
    "btn_yes_cancel": {"te": "అవును, రద్దు", "hi": "हाँ, रद्द करें", "en": "Yes, cancel"},
    "btn_no": {"te": "వద్దు", "hi": "नहीं", "en": "No"},
    "cancelled": {
        "te": "మీ అపాయింట్‌మెంట్ రద్దు చేయబడింది.",
        "hi": "आपका अपॉइंटमेंट रद्द कर दिया गया है।",
        "en": "Your appointment has been cancelled.",
    },
    "resched_confirm": {
        "te": "కొత్త సమయం:\nరోగి: {patient}\nడాక్టర్: {doctor}\nరోజు: {day}\nసమయం: {time}",
        "hi": "नया समय:\nमरीज़: {patient}\nडॉक्टर: {doctor}\nदिन: {day}\nसमय: {time}",
        "en": "New time:\nPatient: {patient}\nDoctor: {doctor}\nDay: {day}\nTime: {time}",
    },
    "rescheduled": {
        "te": "మార్పు అభ్యర్థన అందింది. రిసెప్షన్ కొత్త సమయాన్ని త్వరలో నిర్ధారిస్తుంది.",
        "hi": "बदलाव का अनुरोध मिल गया। रिसेप्शन नया समय जल्द ही पक्का करेगा।",
        "en": "Change requested. Reception will confirm the new time shortly.",
    },
    "change_failed": {
        "te": "క్షమించండి, ఈ అపాయింట్‌మెంట్‌ను మార్చలేను. రిసెప్షన్‌ను సంప్రదించండి.",
        "hi": "माफ़ कीजिए, यह अपॉइंटमेंट बदला नहीं जा सकता। रिसेप्शन से संपर्क करें।",
        "en": "Sorry, this appointment can't be changed. Please contact reception.",
    },
    "handoff": {
        "te": "రిసెప్షన్‌కు తెలియజేశాను. వారు ఇక్కడే మీకు సమాధానం ఇస్తారు.",
        "hi": "मैंने रिसेप्शन को बता दिया है। वे यहीं आपको जवाब देंगे।",
        "en": "I've asked reception to reply to you here. Please wait.",
    },
    "not_understood": {
        "te": "క్షమించండి, అర్థం కాలేదు. దయచేసి ఒక ఎంపికను ఎంచుకోండి.",
        "hi": "माफ़ कीजिए, समझ नहीं आया। कृपया कोई विकल्प चुनें।",
        "en": "Sorry, I didn't understand. Please choose an option.",
    },
    "medical": {
        "te": "నేను అపాయింట్‌మెంట్ సహాయకుడిని, వైద్య సలహా ఇవ్వలేను. దయచేసి డాక్టర్‌ను అడగండి. "
        "అపాయింట్‌మెంట్ బుక్ చేయడంలో సహాయం చేయగలను.",
        "hi": "मैं अपॉइंटमेंट सहायक हूँ और चिकित्सा सलाह नहीं दे सकता। कृपया डॉक्टर से पूछें। "
        "मैं अपॉइंटमेंट बुक करने में मदद कर सकता हूँ।",
        "en": "I'm an appointment assistant and can't give medical advice. Please ask the "
        "doctor. I can help you book an appointment.",
    },
    "emergency": {
        "te": "ఇది అత్యవసర పరిస్థితిలా ఉంది. వెంటనే 108 (అంబులెన్స్) లేదా 112కు కాల్ చేయండి, "
        "లేదా దగ్గరలోని ఆసుపత్రికి వెళ్లండి. మా సిబ్బందికి తెలియజేశాము.",
        "hi": "यह आपात स्थिति लगती है। तुरंत 108 (एम्बुलेंस) या 112 पर कॉल करें, या नज़दीकी "
        "अस्पताल जाएँ। हमने अपने स्टाफ़ को सूचित कर दिया है।",
        "en": "This sounds like an emergency. Please call 108 (ambulance) or 112 right now, "
        "or go to the nearest hospital. We have alerted our staff.",
    },
    "opted_out": {
        "te": "మీరు సందేశాల నుండి తొలగించబడ్డారు. మళ్లీ ఉపయోగించడానికి START పంపండి.",
        "hi": "आपको संदेशों से हटा दिया गया है। फिर से इस्तेमाल करने के लिए START भेजें।",
        "en": "You have been unsubscribed and won't get more messages. Send START to use "
        "the assistant again.",
    },
    "voice_failed": {
        "te": "క్షమించండి, వాయిస్ నోట్ అర్థం కాలేదు. మళ్లీ ప్రయత్నించండి లేదా బటన్లు వాడండి.",
        "hi": "माफ़ कीजिए, वॉइस नोट समझ नहीं आया। फिर से कोशिश करें या बटन इस्तेमाल करें।",
        "en": "Sorry, I couldn't understand the voice note. Please try again or use the buttons.",
    },
    "voice_too_long": {
        "te": "దయచేసి 30 సెకన్ల కంటే తక్కువ వాయిస్ నోట్ పంపండి.",
        "hi": "कृपया 30 सेकंड से छोटा वॉइस नोट भेजें।",
        "en": "Please send a shorter voice note (under 30 seconds).",
    },
    "unsupported": {
        "te": "క్షమించండి, నేను టెక్స్ట్, బటన్లు మరియు వాయిస్ నోట్లు మాత్రమే చదవగలను.",
        "hi": "माफ़ कीजिए, मैं सिर्फ़ टेक्स्ट, बटन और वॉइस नोट पढ़ सकता हूँ।",
        "en": "Sorry, I can only read text, buttons and voice notes.",
    },
    "notice_short": {
        "te": "నమస్కారం! ఇది {clinic} ఆటోమేటెడ్ బుకింగ్ సహాయకుడు. మీ వివరాలు అపాయింట్‌మెంట్ల కోసం "
        "మాత్రమే వాడతాము. ఆపడానికి స్టాప్ అనండి.",
        "hi": "नमस्ते! यह {clinic} का ऑटोमेटेड बुकिंग सहायक है। आपकी जानकारी सिर्फ़ अपॉइंटमेंट "
        "के लिए इस्तेमाल होती है। बंद करने के लिए स्टॉप कहें।",
        "en": "Hello! This is {clinic}'s automated booking assistant. Your details are used "
        "only for appointments. Say stop to opt out.",
    },
    "today": {"te": "ఈరోజు", "hi": "आज", "en": "Today"},
    "tomorrow": {"te": "రేపు", "hi": "कल", "en": "Tomorrow"},
}

# The first message is shown before a language is chosen, so it is trilingual.
NOTICE = (
    "Hello! This is {clinic}'s automated booking assistant. We use your phone number and "
    "the details you share only to manage your appointments. Reply STOP to opt out.\n\n"
    "నమస్కారం! ఇది {clinic} ఆటోమేటెడ్ బుకింగ్ సహాయకుడు. మీ ఫోన్ నంబర్ మరియు మీరు ఇచ్చే "
    "వివరాలు అపాయింట్‌మెంట్ల కోసం మాత్రమే వాడతాము. ఆపడానికి STOP పంపండి.\n\n"
    "नमस्ते! यह {clinic} का ऑटोमेटेड बुकिंग सहायक है। आपका फ़ोन नंबर और आपकी दी हुई "
    "जानकारी सिर्फ़ अपॉइंटमेंट के लिए इस्तेमाल होती है। बंद करने के लिए STOP भेजें।\n\n"
    "Choose a language / భాష ఎంచుకోండి / भाषा चुनें"
)
LANGUAGE_TITLES: dict[Language, str] = {"te": "తెలుగు", "hi": "हिंदी", "en": "English"}

REASONS = ("general", "fever", "followup", "pain", "child", "other")

WEEKDAYS: dict[Language, tuple[str, ...]] = {
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "hi": ("सोम", "मंगल", "बुध", "गुरु", "शुक्र", "शनि", "रवि"),
    "te": ("సోమ", "మంగళ", "బుధ", "గురు", "శుక్ర", "శని", "ఆది"),
}
MONTHS: dict[Language, tuple[str, ...]] = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "hi": (
        "जन",
        "फ़र",
        "मार्च",
        "अप्रै",
        "मई",
        "जून",
        "जुला",
        "अग",
        "सित",
        "अक्टू",
        "नव",
        "दिस",
    ),
    "te": (
        "జన",
        "ఫిబ్ర",
        "మార్చి",
        "ఏప్రి",
        "మే",
        "జూన్",
        "జులై",
        "ఆగ",
        "సెప్టెం",
        "అక్టో",
        "నవం",
        "డిసెం",
    ),
}


def t(lang: Language | None, key: str, **values: object) -> str:
    text = CATALOG[key][lang or "en"]
    return text.format(**values) if values else text


def english(key: str) -> str:
    return CATALOG[key]["en"]


def day_label(lang: Language | None, day: date, today: date) -> str:
    language = lang or "en"
    base = f"{WEEKDAYS[language][day.weekday()]} {day.day} {MONTHS[language][day.month - 1]}"
    if day == today:
        return f"{t(lang, 'today')}, {base}"
    if (day - today).days == 1:
        return f"{t(lang, 'tomorrow')}, {base}"
    return base


def time_label(moment: datetime, tz: ZoneInfo) -> str:
    return moment.astimezone(tz).strftime("%I:%M %p").lstrip("0")


def first_name(full_name: str) -> str:
    parts = full_name.split()
    return parts[0] if parts else full_name
