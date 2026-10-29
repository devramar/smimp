# Productive-Commits
This repository is to explain the concept of Productive Commits.
Productive Commits are an attempt to conjoin the two worlds of handling commits i've seen attempted to be used in the wild

## World one: Commits as a Development Tool
This world is about enabling the developer to make as many commits as possible, and to use git as a version management tool while in active development.
Little care is intended for individual commits, and meaning is obtained from the broader merging strategies.

## World two: Commits as a project management tool
This world is about using things such as pre-commit hooks or commit message schemes to enable productivity within the project. 

## What Productive Commits are Meant to Be (For my purpose, at least)
I have qualms with both of these worlds, and they both have their own pros and cons. 
What Productive Commits are intended as are a way to bridge these two by using an optional commit message schema that's human readable & machine readable.
The idea here is that you can commit as much as you'd like with normal messages for your own personal use, but when you have something productive you've done to your repository, you stage a productive commit.

Using this idea, we now have more control over our repository, some arbitrary examples I plan on using:
 - We can wrap our pre-commit hooks so that they only run on a Productive Commit
 - When trying to analyse what might be included for something like a changelog, we can exclusive read productive commits, as they should be the only things containing pertinent broader information.

# Productive Commits In Practise
Enough rambling about my intentions, here's how a Productive Commit Looks:
```
Optional higher level information / commit title
as many newlines as you'd like, this header here is considered whitespace.
A Name of a Scope Or Project or Grouping: (optional message)
 - Some useful message underlying a change you did specifically here
 - Some more information
   - Some sub-information (note, # of spaces is increased)
      - Some even-subber information (spaces > previous line)
      - An extra related note here (spaces == previous line)

This is another section I'd like to write about: (i use these as personal comments!)
 - Relevant information for this section of the repository
   - Can repeat everything the previous section can
         - this is still associated to the above line, all that matters is spaces > previous line
      - this is on the same level as the previous line, this is mainly a human writing error handling precaution
       - and *now* this line is a sub-line of the previous line.

More whitespace that is unrelated to the project etc.
```
The idea here is a tree structure of messages. Each Productive Commit may have multiple heirarchies sorted by their project.

You start with your projects:
  - You then have your main points you've done
     - And if you need to, you can get more specific, too.
     - Or explain multiple related things as you need.

## A Running Example
Pretend we're making a website & mobile app for "Pizza Brand"(TM) and have been instructed to use one git repository, using sub-projects for our frontend, middleware & backend.

Our PM has forced us beyond any reasonable thinking to have:
- one project for the website
- one project for the mobile app
- our middleware is one project
- our backend is one project

A productive commit may look like this:
```
we're so close to buying pizzas now! 1.0 bound baby 😎
Mobile App:
 - Resolved bug in cart system
 - Wireframed checkout screen to follow UI specification.
    - Connected purchase button to local API call.

Middleware:
 - Created purchase button workflow to interact with the Backend.
 - Started work on receipt formatting
   - Just need to polish how we actually place everything... the app doesn't like long receipts right now.

Backend:
 - Implemented transaction history & receipt system following spec.
 - Added basic endpoints to be able to create a transaction that creates a receipt, up to middleware to make the receipt look good now.
```


# So That's All?
For now, yes. 
In the future, I plan for this repository to contain code snippets to be able to parse the git tree and receive these Productive Commits, and potentially this repo can be a place you can quickly grab the right pre-commit hook integration or snippet you need to get your project running.

But I'm only one man, and I don't have the time right now to do that. If you'd like to contribute, Forks are welcome!