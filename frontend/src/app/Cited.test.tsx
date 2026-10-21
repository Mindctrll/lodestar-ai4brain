import { fireEvent, render, screen } from '@testing-library/react'

import { Cited } from './Cited'

test('citations become chips, and a decision citation opens its card', () => {
  const opened: string[] = []
  render(
    <p>
      <Cited
        text="Memory is the skill I'm least sure about [D1]. You got 8 of 10 right [F1, F2]."
        refs={{ D1: 'decision-7' }}
        onWhy={(id) => opened.push(id)}
      />
    </p>,
  )
  expect(screen.getByText('F1')).toBeTruthy()
  expect(screen.getByText('F2')).toBeTruthy()
  expect(screen.queryByText(/\[/)).toBeNull() // no raw brackets left
  fireEvent.click(screen.getByRole('button', { name: 'Why? (D1)' }))
  expect(opened).toEqual(['decision-7'])
})

test('without refs every citation is a plain chip', () => {
  render(<Cited text="Goal set [F1]." />)
  expect(screen.queryByRole('button')).toBeNull()
  expect(screen.getByText('F1').tagName).toBe('SPAN')
})
