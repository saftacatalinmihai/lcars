## 9. The crew {#crew}

The crew are Claude engineers who work on the app itself, under Number One, run from the console. You talk to them in the console's chats, in rooms, and in crew notes written in your entries.

The crew need setting up on the server. Until then, the **Crew**{ui} section of the Chats list shows one row, **The crew**, which asks for the engineer key.

### Who is who

- **Number One**{ui} is your first officer. It gives the engineers their orders and reviews their work, so most of the time you talk to Number One and it does the rest.
- **An engineer** is one Claude Code session that changes the app, on a branch of its own. Each has a name and a conversation.
- **The seat**: one engineer works at a time. A message to an engineer who is not in the seat waits, marked **queued · for the seat**, and is delivered when their turn comes.
- **Crew roles**, such as the yeoman, run on a schedule and write reports. Their reports are in the **Reports**{ui} section of the Chats list, where you can talk each one over.

What the crew write in the journal is hidden from your list until you show it (**H**).

### Give an order

- **To Number One**: open **Number One**{ui} in the Chats list and write. This is the usual way.
- **To an engineer**: open their conversation and write.
- **A new engineer**: type a name in **add an engineer**{ui}, at the bottom of the Chats list, and tap **Add engineer**{ui}. **Dismiss**{ui}, on their row, stops them and takes them off the list, with everything kept; **Bring back**{ui} returns them.

A badge on each row says where they stand. Three dots: they are working. **#1 SEAT**{ui}, **#2 SEAT**{ui}: their place in line for the seat. **ANSWER**{ui}: a question of theirs waits for you.

### Rooms

**Rooms**{ui}, in the Crew section, shows the crew's messages as one timeline per room. A project room holds one piece of work: your order, Number One's orders to the engineers, their reports, and the deploys.

- **+** makes a new room.
- What you write in a room goes to Number One. The **To** chip beside **Send**{ui} picks an engineer instead.
- Each message links to its place in the full conversation.

![A project room on a phone: the captain's order, Number One's order to an engineer, the engineer's report, and the ship's deploy line; the message box with + , To No.1 and Send at the bottom.](img/room.webp "A project room, from the order to the deploy.")

### Answer what the crew ask

**Open questions**{ui} (at the top of the Chats list, or **!**) holds what Number One and the crew ask of you. Each question has its context, its choices and the recommended one.

1. Tap a choice for each question, or **Skip**{ui}. Add **a note (optional)**{ui} if you want.
2. Tap **Send**{ui}, once every question has an answer. Your answers are written at the top of the question's entry and it is closed; Number One is told.
3. **Undo**{ui}, in the message, opens it again.

**Later**{ui} puts a question away on this device for an hour, three hours, or until tomorrow at 9:00.

![Open questions on a phone: a card from Number One with two questions, the choices A, B and C with A recommended, Yes and No with No recommended, Skip, a note box, and Later and Send.](img/questions.webp "Open questions. The recommended choice is marked.")

### Write a crew note in an entry

In any entry of yours, start a line with `@no1`, an engineer's name, or a crew role that takes notes, such as `@yeoman`, then the order:

`@yeoman log a gym session from 18:00 to 19:00`

The one you named answers beside that line, and you can reply there. **Crew notes**{ui}, in the Reports section of the Chats list, has every thread. A role changes your entries only when the note asks it to; "computer, undo the crew's changes" takes its newest changes back.

### See who works on what

**Queue & shipped**{ui} (or **Q**) shows who has the seat and on what, who waits for it with which order, and every deploy, newest first, with its version.

### Deploy an engineer's work

Deploying puts an engineer's work into the app you are using.

1. Open the engineer's conversation, then **⋯**, and tap **Deploy**{ui}. Usually Number One deploys the work once it has reviewed it; this is for when you want to do it yourself.
2. The console asks "Deploy Chief Reyes's work?" (with the engineer's name) and names the branch, its commits and the last one. The work is tested and put into the live app, and the server rebuilt if needed.
3. Tap **Deploy**{ui}. **The deploy changes the running app, for every device, as soon as it finishes.** The conversation shows its progress and how it ended.

If something is wrong afterwards, **Roll back**{ui}, in the same ⋯ sheet, reverts the last deploy. It asks "Roll back the last deploy?" first.

### Related

- [Chats with the computer](#chat)
- [Pictures, recordings and reports](#media)
- [Offline, updates and settings](#settings)
