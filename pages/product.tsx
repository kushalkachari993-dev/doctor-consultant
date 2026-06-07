"use client"

import { useState, FormEvent } from 'react';
import { useAuth, useUser } from '@clerk/nextjs';
import DatePicker from 'react-datepicker';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { Protect, PricingTable, UserButton } from '@clerk/nextjs';

type StreamMessage = {
    content?: string;
    error?: string;
};

type SendEmailResponse = {
    audit_id: string;
    content_version: string;
    provider_message_id?: string;
};

async function responseErrorMessage(response: Response, fallback: string) {
    const contentType = response.headers.get('content-type') ?? '';

    if (contentType.includes('application/json')) {
        const body = await response.json() as { detail?: string };
        return body.detail ?? fallback;
    }

    return `${fallback} (${response.status} ${response.statusText})`;
}

function ConsultationForm() {
    const { getToken } = useAuth();
    const { user } = useUser();
    const doctorEmail = user?.primaryEmailAddress?.emailAddress ?? '';

    const [patientName, setPatientName] = useState('');
    const [patientEmail, setPatientEmail] = useState('');
    const [visitDate, setVisitDate] = useState<Date | null>(new Date());
    const [notes, setNotes] = useState('');
    const [output, setOutput] = useState('');
    const [loading, setLoading] = useState(false);
    const [sendStatus, setSendStatus] = useState('');
    const [sendingEmail, setSendingEmail] = useState(false);

    function patientEmailDraft() {
        const heading = '### Draft of email to patient in patient-friendly language';
        const headingIndex = output.indexOf(heading);

        if (headingIndex === -1) {
            return '';
        }

        return output.slice(headingIndex + heading.length).trim();
    }

    async function handleSubmit(e: FormEvent) {
        e.preventDefault();
        setOutput('');
        setSendStatus('');
        setLoading(true);

        const jwt = await getToken();
        if (!jwt) {
            setOutput('Authentication required.');
            setLoading(false);
            return;
        }

        const controller = new AbortController();
        let buffer = '';

        try {
            await fetchEventSource('/api', {
                signal: controller.signal,
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${jwt}`,
                },
                body: JSON.stringify({
                    patient_name: patientName.trim(),
                    patient_email: patientEmail.trim(),
                    date_of_visit: visitDate?.toISOString().slice(0, 10),
                    notes: notes.trim(),
                }),
                async onopen(response) {
                    if (!response.ok) {
                        throw new Error(
                            await responseErrorMessage(response, 'Unable to generate the consultation summary.')
                        );
                    }
                },
                onmessage(ev) {
                    const message = JSON.parse(ev.data) as StreamMessage;
                    if (message.error) {
                        throw new Error(message.error);
                    }
                    buffer += message.content ?? '';
                    setOutput(buffer);
                },
                onerror(err) {
                    throw err;
                },
            });
        } catch (err) {
            console.error('SSE error:', err);
            controller.abort();
            setOutput(err instanceof Error ? err.message : 'Unable to generate the consultation summary.');
        } finally {
            setLoading(false);
        }
    }

    async function handleSendEmail() {
        const draft = patientEmailDraft();

        if (!draft) {
            setSendStatus('Generate a patient email draft before sending.');
            return;
        }

        if (!doctorEmail) {
            setSendStatus('Your signed-in account needs a primary email address before sending.');
            return;
        }

        const confirmed = window.confirm(
            `Send this reviewed email draft from ${doctorEmail} to ${patientEmail}? This action will be recorded in the audit log.`
        );

        if (!confirmed) {
            return;
        }

        setSendingEmail(true);
        setSendStatus('');

        try {
            const jwt = await getToken();
            if (!jwt) {
                throw new Error('Authentication required.');
            }

            const response = await fetch('/api/send_email', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${jwt}`,
                },
                body: JSON.stringify({
                    doctor_email: doctorEmail,
                    patient_name: patientName.trim(),
                    patient_email: patientEmail.trim(),
                    email_body: draft,
                    generated_content: output,
                }),
            });

            if (!response.ok) {
                throw new Error(await responseErrorMessage(response, 'Unable to send the email.'));
            }

            const result = await response.json() as SendEmailResponse;
            setSendStatus(`Email sent. Audit id: ${result.audit_id}. Version: ${result.content_version}.`);
        } catch (err) {
            console.error('Email send error:', err);
            setSendStatus(err instanceof Error ? err.message : 'Unable to send the email.');
        } finally {
            setSendingEmail(false);
        }
    }

    return (
        <div className="container mx-auto px-4 py-12 max-w-3xl">
            <h1 className="text-4xl font-bold text-gray-900 dark:text-gray-100 mb-8">
                Consultation Notes
            </h1>

            <form onSubmit={handleSubmit} className="space-y-6 bg-white dark:bg-gray-800 rounded-xl shadow-lg p-8">
                <div className="space-y-2">
                    <label htmlFor="patient" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                        Patient Name
                    </label>
                    <input
                        id="patient"
                        type="text"
                        required
                        value={patientName}
                        onChange={(e) => setPatientName(e.target.value)}
                        className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:text-white"
                        placeholder="Enter patient's full name"
                    />
                </div>

                <div className="space-y-2">
                    <label htmlFor="patient-email" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                        Recipient Email
                    </label>
                    <input
                        id="patient-email"
                        type="email"
                        required
                        value={patientEmail}
                        onChange={(e) => setPatientEmail(e.target.value)}
                        className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:text-white"
                        placeholder="Enter recipient email address"
                    />
                </div>

                <div className="space-y-2">
                    <label htmlFor="date" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                        Date of Visit
                    </label>
                    <DatePicker
                        id="date"
                        selected={visitDate}
                        onChange={(d: Date | null) => setVisitDate(d)}
                        dateFormat="yyyy-MM-dd"
                        placeholderText="Select date"
                        required
                        className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:text-white"
                    />
                </div>

                <div className="space-y-2">
                    <label htmlFor="notes" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                        Consultation Notes
                    </label>
                    <textarea
                        id="notes"
                        required
                        rows={8}
                        value={notes}
                        onChange={(e) => setNotes(e.target.value)}
                        className="w-full px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:text-white"
                        placeholder="Enter detailed consultation notes..."
                    />
                </div>

                <button
                    type="submit"
                    disabled={loading}
                    className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white font-semibold py-3 px-6 rounded-lg transition-colors duration-200"
                >
                    {loading ? 'Generating Summary...' : 'Generate Summary'}
                </button>
            </form>

            {output && (
                <section className="mt-8 bg-gray-50 dark:bg-gray-800 rounded-xl shadow-lg p-8">
                    <div className="markdown-content prose prose-blue dark:prose-invert max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
                            {output}
                        </ReactMarkdown>
                    </div>
                    <div className="mt-8 border-t border-gray-200 pt-6 dark:border-gray-700">
                        <button
                            type="button"
                            onClick={handleSendEmail}
                            disabled={loading || sendingEmail || !patientEmailDraft() || !doctorEmail}
                            className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-400 text-white font-semibold py-3 px-6 rounded-lg transition-colors duration-200"
                        >
                            {sendingEmail ? 'Sending Email...' : 'Send Email'}
                        </button>
                        {sendStatus && (
                            <p className="mt-3 text-sm text-gray-600 dark:text-gray-300">
                                {sendStatus}
                            </p>
                        )}
                    </div>
                </section>
            )}
        </div>
    );
}

export default function Product() {
    return (
        <main className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100 dark:from-gray-900 dark:to-gray-800">
            <div className="absolute top-4 right-4">
                <UserButton showName={true} />
            </div>

            <Protect
                plan="premium_subscription"
                fallback={
                    <div className="container mx-auto px-4 py-12">
                        <header className="text-center mb-12">
                            <h1 className="text-5xl font-bold bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-transparent mb-4">
                                Healthcare Professional Plan
                            </h1>
                            <p className="text-gray-600 dark:text-gray-400 text-lg mb-8">
                                Streamline your patient consultations with AI-powered summaries
                            </p>
                        </header>
                        <div className="max-w-4xl mx-auto">
                            <PricingTable />
                        </div>
                    </div>
                }
            >
                <ConsultationForm />
            </Protect>
        </main>
    );
}
