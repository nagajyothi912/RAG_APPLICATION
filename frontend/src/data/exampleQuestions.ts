/**
 * Example questions for the MCP assistant, shared by the customer chatbot, the
 * admin Week 9 lab and the admin home's common questions. The golden set comes
 * from the backend (/api/golden-questions); these are the ticket-side ones it
 * does not cover.
 */

export const TICKET_QUESTIONS = [
  'Which support tickets are open right now?',
  'Has anyone called back the customer on ticket TCK-4471?',
  'What is happening with the relocation complaint that has been open for six weeks?',
];

export const ASSISTANT_EXAMPLES = [
  'Has anyone called back the customer on ticket TCK-4471?',
  'What is happening with the relocation complaint that has been open for six weeks?',
  'Customer on TCK-4518 wants a full refund for the outage. What happened and what does our policy allow?',
  'What does a blinking red LED on my router mean?',
  'Look up ticket 4471',
];
