import { useState, useEffect, useRef } from 'react';

export default function Home() {
    const [sessionId, setSessionId] = useState(null);
    const [currentQuestion, setCurrentQuestion] = useState('');
    const [conversationLog, setConversationLog] = useState([]);
    const [candidateName, setCandidateName] = useState('');
    const [scenarioScore, setScenarioScore] = useState(null);
    const [isRecording, setIsRecording] = useState(false);
    const [timer, setTimer] = useState(45);
    const [mediaRecorder, setMediaRecorder] = useState(null);
    const [audioBlob, setAudioBlob] = useState(null);
    const timerRef = useRef(null);

    useEffect(() => {
        if (isRecording) {
            timerRef.current = setInterval(() => {
                setTimer(prev => {
                    if (prev <= 1) {
                        clearInterval(timerRef.current);
                        stopRecording();
                        return 45;
                    }
                    return prev - 1;
                });
            }, 1000);
        } else if (timerRef.current) {
            clearInterval(timerRef.current);
            setTimer(45);
        }

        return () => clearInterval(timerRef.current);
    }, [isRecording]);

    const startInterview = async () => {
        if (!candidateName) {
            alert('Please enter your name');
            return;
        }

        try {
            const response = await fetch('http://localhost:8000/start_interview', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ candidate_name: candidateName }),
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            setSessionId(data.session_id);
            displayQuestion(data.question);
            speakQuestion(data.question);
        } catch (error) {
            console.error('Error:', error);
            alert('An error occurred while starting the interview. Please try again.');
        }
    };

    const displayQuestion = (question) => {
        setCurrentQuestion(question);
        logConversation('System', question);
    };

    const speakQuestion = (text) => {
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.voice = speechSynthesis.getVoices().find(voice => voice.name === 'Microsoft David Desktop - English (United States)');
        speechSynthesis.speak(utterance);
    };

    const startRecording = async () => {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert('Media Devices API not supported.');
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const recorder = new MediaRecorder(stream);
            const chunks = [];

            recorder.ondataavailable = (event) => {
                chunks.push(event.data);
            };

            recorder.onstop = () => {
                const blob = new Blob(chunks, { type: 'audio/wav' }); // Change to 'audio/wav'
                setAudioBlob(blob);
                submitResponse(blob);
            };

            recorder.start();
            setIsRecording(true);
            setMediaRecorder(recorder);
        } catch (error) {
            console.error('Error starting recording:', error);
            alert('An error occurred while starting recording.');
        }
    };

    const stopRecording = () => {
        if (mediaRecorder) {
            mediaRecorder.stop();
            setIsRecording(false);
        }
    };

    const submitResponse = async (blob) => {
        if (!sessionId) {
            alert('Session ID is missing.');
            return;
        }
    
        try {
            const formData = new FormData();
            formData.append('session_id', sessionId);
            formData.append('audio_file', blob, 'audio.wav'); // Ensure filename is correct
    
            console.log('Submitting audio file with size:', blob.size); // Log file size
            console.log('Submitting audio file with type:', blob.type); // Log file type
    
            const response = await fetch('http://localhost:8000/submit_response', {
                method: 'POST',
                body: formData,
            });
    
            if (!response.ok) {
                const errorText = await response.text();
                console.error('HTTP error! Status:', response.status, 'Response:', errorText);
                throw new Error(`HTTP error! status: ${response.status}`);
            }
    
            const data = await response.json();
            console.log('Transcription response:', data); // Log the response data
    
            logConversation('Candidate', 'Audio response submitted.');
    
            if (data.message === 'Interview completed') {
                alert('Interview completed. Thank you for your participation!');
                resetInterview();
            } else {
                displayQuestion(data.question);
                if (data.score) {
                    setScenarioScore(data.score);
                    logConversation('System', `Scenario score: ${data.score}`);
                }
                if (data.message) {
                    logConversation('System', data.message);
                }
            }
        } catch (error) {
            console.error('Error:', error);
            alert('An error occurred while submitting your response.');
        }
    };

    const logConversation = (speaker, text) => {
        setConversationLog(prevLog => [...prevLog, { speaker, text }]);
    };

    const resetInterview = () => {
        setSessionId(null);
        setCandidateName('');
        setCurrentQuestion('');
        setConversationLog([]);
        setScenarioScore(null);
        setAudioBlob(null);
        if (mediaRecorder) {
            mediaRecorder.stop();
        }
    };

    return (
        <div>
            <h1>Interview System</h1>

            {!sessionId && (
                <div id="startContainer">
                    <input
                        type="text"
                        id="candidateName"
                        placeholder="Enter your name"
                        value={candidateName}
                        onChange={(e) => setCandidateName(e.target.value)}
                    />
                    <button onClick={startInterview}>Start Interview</button>
                </div>
            )}

            {sessionId && (
                <div id="interviewContainer">
                    <h2>Current Question:</h2>
                    <p>{currentQuestion}</p>
                    <button onClick={startRecording} disabled={isRecording}>
                        Start Recording
                    </button>
                    <button onClick={stopRecording} disabled={!isRecording}>
                        Stop Recording
                    </button>
                    <p>Time remaining: {timer} seconds</p>
                    {scenarioScore && <p>Scenario Score: {scenarioScore}</p>}
                </div>
            )}

            <div id="conversationLog">
                {conversationLog.map((entry, index) => (
                    <p key={index} className={`${entry.speaker.toLowerCase()}-message`}>
                        <strong>{entry.speaker}:</strong> {entry.text}
                    </p>
                ))}
            </div>

            <style jsx>{`
                body {
                    font-family: Arial, sans-serif;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                }
                #interviewContainer {
                    display: ${sessionId ? 'block' : 'none'};
                }
                #conversationLog {
                    margin-top: 20px;
                    border: 1px solid #ccc;
                    padding: 10px;
                    height: 300px;
                    overflow-y: scroll;
                }
                .system-message {
                    color: #0066cc;
                }
                .candidate-message {
                    color: #006600;
                }
            `}</style>
        </div>
    );
}
