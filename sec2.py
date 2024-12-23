import gymnasium as gym
from gymnasium.envs.toy_text.frozen_lake import generate_random_map
import numpy as np
from collections import defaultdict
from tqdm import tqdm
import pickle
import torch
from collections import deque
import collections

collections.Callable = collections.abc.Callable

import torch.nn as nn
import torch.optim as optim
import wandb
import random
import os

# os.environ["WANDB_DISABLE_CODE"]="true"
wandb.setup(wandb.Settings(program="Q2.py", program_relpath="Q2.py"))
wandb.login(key="--")


class DQN3Layers(nn.Module):
    def __init__(self, state_size, action_size=2):
        super(DQN3Layers, self).__init__()
        self.network = nn.Sequential(
            nn.Linear(state_size, 32),  # Input layer to first hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # First hidden layer to second hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # Second hidden layer to third hidden layer
            nn.ReLU(),
            nn.Linear(32, action_size)  # Third hidden layer to output layer
        )

    def forward(self, state):
        return self.network(state)


class DQN5Layers(nn.Module):
    def __init__(self, state_size, action_size=2):
        super(DQN5Layers, self).__init__()
        self.network = nn.Sequential(
            nn.Linear(state_size, 32),  # Input layer to first hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # First hidden layer to second hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # Second hidden layer to third hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # Third hidden layer to fourth hidden layer
            nn.ReLU(),
            nn.Linear(32, 32),  # Fourth hidden layer to fifth hidden layer
            nn.ReLU(),
            nn.Linear(32, action_size)  # Fifth hidden layer to output layer
        )

    def forward(self, state):
        return self.network(state)


# Agent Class
class CAgent:
    def __init__(self, env, model, learning_rate, initial_epsilon, epsilon_decay, final_epsilon, discount_factor):
        self.env = env
        self.model = model
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)

        if model_class.__name__ == "DQN3Layers":
            self.target_model = DQN3Layers(env.observation_space.shape[0], env.action_space.n).to(self.device)
            self.target_model.load_state_dict(self.model.state_dict())
        else:
            self.target_model = DQN5Layers(env.observation_space.shape[0], env.action_space.n).to(self.device)
            self.target_model.load_state_dict(self.model.state_dict())
        self.target_model.eval()

        self.optimizer = optim.Adam(self.model.parameters(), lr=learning_rate)
        self.criterion = nn.MSELoss()
        self.replay_memory = deque(maxlen=10000)

        self.epsilon = initial_epsilon
        self.epsilon_decay = epsilon_decay
        self.final_epsilon = final_epsilon
        self.discount_factor = discount_factor

    def sample_action(self, state):
        if np.random.random() < self.epsilon:
            return self.env.action_space.sample()
        state_tensor = torch.FloatTensor(state).to(self.device).unsqueeze(0)
        with torch.no_grad():
            return torch.argmax(self.model(state_tensor)).item()

    def test_action(self, state):
        state_tensor = torch.FloatTensor(state).to(self.device).unsqueeze(0)
        with torch.no_grad():
            return torch.argmax(self.model(state_tensor)).item()

    def decay_epsilon(self):
        self.epsilon = max(self.final_epsilon, self.epsilon * (1 - self.epsilon_decay))

    def store_experience(self, experience):
        self.replay_memory.append(experience)

    def sample_batch(self, batch_size):
        return random.sample(self.replay_memory, batch_size)

    def update_target_model(self):
        self.target_model.load_state_dict(self.model.state_dict())

    def train_on_batch(self, batch_size):
        if len(self.replay_memory) < batch_size:
            return None
        batch = self.sample_batch(batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)

        states = torch.FloatTensor(np.array(states)).to(self.device)
        actions = torch.LongTensor(actions).to(self.device)
        rewards = torch.FloatTensor(rewards).to(self.device)
        next_states = torch.FloatTensor(next_states).to(self.device)
        dones = torch.FloatTensor(dones).to(self.device)

        current_q_values = self.model(states).gather(1, actions.unsqueeze(-1)).squeeze(-1)
        with torch.no_grad():
            max_next_q_values = self.target_model(next_states).max(1)[0]
            target_q_values = rewards + (1 - dones) * self.discount_factor * max_next_q_values

        loss = self.criterion(current_q_values, target_q_values)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        return loss.item()


env = gym.make('CartPole-v1')


# write a test function to test the agent, this function will be called while training the agent
def test_agent(env, agent, episodes=100):
    rewards = []
    for episode in range(episodes):
        state, _ = env.reset()
        total_reward = 0
        for t in range(500):
            action = agent.test_action(state)
            next_state, reward, done, truncated, _ = env.step(action)
            state = next_state
            total_reward += reward
            if done:
                break
        rewards.append(total_reward)
    return rewards


# Training Function
def train_agent(env, agent, episodes, batch_size, target_update_every):
    rewards = []
    losses = []

    for episode in range(episodes):
        state, _ = env.reset()
        total_reward = 0
        episode_losses = []
        done = False
        truncated = False
        first_time_passed = 8000
        while not (done or truncated):
            action = agent.sample_action(state)
            next_state, reward, done, truncated, _ = env.step(action)
            agent.store_experience((state, action, reward, next_state, done))
            state = next_state
            total_reward += reward

            if len(agent.replay_memory) >= batch_size:
                loss = agent.train_on_batch(batch_size)
                if loss is not None:
                    episode_losses.append(loss)

                if done:
                    break

        agent.decay_epsilon()
        rewards.append(total_reward)
        losses.extend(episode_losses)

        if episode % target_update_every == 0:
            agent.update_target_model()

        if episode % 50 == 0:
            agent.model.eval()
            test_rewards = test_agent(env, agent)
            wandb.log({"test_reward": np.mean(test_rewards)})
            if (np.mean(test_rewards) > 475) and (first_time_passed == 8000):
                first_time_passed = episode
            agent.model.train()


        wandb.log({"Reward": total_reward, "Loss": np.mean(episode_losses)})

        print(f"Episode {episode} - Reward: {total_reward}, Loss: {np.mean(episode_losses):.4f}")

    avg_reward = np.mean(rewards[-100:])
    return first_time_passed


# Hyperparameter Optimization Loop
env = gym.make("CartPole-v1")
state_size = env.observation_space.shape[0]
action_size = env.action_space.n

learning_rates = [0.01, 0.0001]
epsilon_decays = [0.01, 0.1]
discount_factors = [0.9, 0.99, 0.95]
batch_sizes = [1024, 2048]
models = [DQN3Layers, DQN5Layers]

best_config = None
best_avg_reward = -float("inf")

for lr in learning_rates:
    for epsilon_decay in epsilon_decays:
        for discount_factor in discount_factors:
            for batch_size in batch_sizes:
                for model_class in models:
                    # Start a new Wandb run for each configuration
                    wandb.init(
                        project="DRL_HW2_Q2",
                        name=f"Model={model_class.__name__}_LR={lr}_ED={epsilon_decay}_DF={discount_factor}_BS={batch_size}",
                        #
                        config={
                            "learning_rate": lr,
                            "epsilon_decay": epsilon_decay,
                            "discount_factor": discount_factor,
                            "batch_size": batch_size,
                            "model": model_class.__name__,
                        },
                        reinit=True,  # Allows multiple runs in a loop
                    )

                    agent = CAgent(
                        env,
                        model_class(state_size, action_size),
                        learning_rate=lr,
                        initial_epsilon=1.0,
                        epsilon_decay=epsilon_decay,
                        final_epsilon=0.01,
                        discount_factor=discount_factor,
                    )

                    rewards, losses, avg_reward = train_agent(env, agent, episodes=1200, batch_size=batch_size,
                                                              target_update_every=2)

                    if avg_reward > best_avg_reward:
                        best_avg_reward = avg_reward
                        best_config = {
                            "learning_rate": lr,
                            "epsilon_decay": epsilon_decay,
                            "discount_factor": discount_factor,
                            "batch_size": batch_size,
                            "model": model_class.__name__,
                        }

                    print(
                        f"Config: LR={lr}, ED={epsilon_decay}, DF={discount_factor}, BS={batch_size}, Model={model_class.__name__}")
                    print(f"Average Reward: {avg_reward}, Best Reward: {best_avg_reward}")
                    with open("results.txt", "a") as f:
                        f.write(
                            f"Config: LR={lr}, ED={epsilon_decay}, DF={discount_factor}, BS={batch_size}, Model={model_class.__name__}\n")
                        f.write(f"Average Reward: {avg_reward}, Best Reward: {best_avg_reward}\n")

                    wandb.finish()  # End the current Wandb run

print(f"Best Configuration: {best_config}")